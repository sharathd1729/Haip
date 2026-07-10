"""
AI Concierge draft task — generates WhatsApp reply using brand-voice + KB RAG.
In shadow mode: stores as ai_drafted=True, awaits agent approval.
In autonomous mode: queues send_whatsapp directly.
"""
import asyncio
import json
import uuid
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.inquiry import Inquiry
from app.adapters.llm import get_llm


def _run_async(coro):
    """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
from app.services.concierge_service import build_concierge_context, _kb_search
from app.core.database import set_tenant_context
import structlog

MODEL_HAIKU = "claude-haiku-4-5"

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

CONCIERGE_TOOL = {
    "name": "concierge_reply",
    "description": "Draft a WhatsApp reply for the guest",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "confidence": {"type": "number"},
            "citations": {"type": "array", "items": {"type": "string"}},
            "needs_human": {"type": "boolean"},
            "reason_needs_human": {"type": ["string", "null"]},
        },
        "required": ["reply", "confidence", "needs_human"],
    },
}

CONFIDENCE_THRESHOLD = 0.78


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="tasks.concierge_draft")
def concierge_draft(self, message_id: str, conversation_id: str, tenant_id: str):
    from app.workers.tasks.send_whatsapp import send_whatsapp
    from app.workers.tasks.send_instagram_dm import send_instagram_dm

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        conversation = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first()
        if not conversation:
            log.error("concierge_draft_conversation_not_found", conversation_id=conversation_id)
            return

        guest_id = conversation.guest_id
        ctx = build_concierge_context(db, tenant_id=tenant_id, conversation_id=conversation_id, guest_id=guest_id, message_id=message_id)

        guest = ctx["guest"]
        tenant = ctx["tenant"]
        inquiry = ctx["inquiry"]

        template = _jinja_env.get_template("concierge_reply.jinja")

        # Render with context
        class TenantProxy:
            def __init__(self, t):
                self.brand_name = t.brand_name or t.name
                self.brand_config = t.brand_config or {}
                self.name = t.name

        system_prompt = template.render(
            tenant=TenantProxy(tenant),
            guest=guest,
            inquiry=inquiry,
            recent_messages=ctx["recent_messages"],
            call_summaries=ctx["call_summaries"],
            kb_snippets=ctx["kb_snippets"],
        )

        adapter = get_llm("concierge_draft")
        result = _run_async(
            adapter.complete(
                system_prompt=system_prompt,
                user_message="Draft a reply for this guest.",
                model=MODEL_HAIKU,
                tools=[CONCIERGE_TOOL],
            )
        )
        draft = result.get("tool_use") or {}
        confidence = draft.get("confidence", 0.0)
        reply_text = draft.get("reply", "")
        needs_human = draft.get("needs_human", True)

        # Determine mode
        ai_mode = conversation.ai_mode or "shadow"
        should_auto_send = (ai_mode == "autonomous" and confidence >= CONFIDENCE_THRESHOLD and not needs_human)

        # Store the drafted message
        draft_message = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            channel=conversation.channel,
            body=reply_text,
            is_ai_generated=True,
            ai_confidence=confidence,
            was_approved=True if should_auto_send else None,
            sender_name="AI Concierge",
        )
        db.add(draft_message)
        db.commit()

        log.info("concierge_draft_stored", message_id=draft_message.id, confidence=confidence, auto_send=should_auto_send)

        if should_auto_send:
            channel_val = str(conversation.channel.value if hasattr(conversation.channel, "value") else conversation.channel)
            if channel_val == "instagram":
                send_instagram_dm.delay(message_id=draft_message.id, tenant_id=tenant_id)
            else:
                send_whatsapp.delay(message_id=draft_message.id, tenant_id=tenant_id)
        else:
            # Push SSE notification to inbox
            _emit_sse(tenant_id=tenant_id, event="ai_draft_ready", conversation_id=conversation_id)
            # Push notification (browser closed / mobile PWA)
            try:
                from app.services.push_service import send_to_tenant
                send_to_tenant(
                    db=db,
                    tenant_id=tenant_id,
                    title="AI draft ready for review",
                    body="A reply has been drafted and is waiting for your approval.",
                    url=f"/dashboard/inbox?id={conversation_id}",
                    tag="haip-draft",
                    user_id=conversation.assigned_to or None,
                )
            except Exception as _push_exc:
                log.warning("push_notify_failed", error=str(_push_exc))

        # Leads360: trigger debounced AI summary refresh for linked inquiry
        if inquiry and inquiry.id:
            try:
                from app.services.leads_service import trigger_summary_refresh
                trigger_summary_refresh(
                    db=db,
                    inquiry_id=str(inquiry.id),
                    tenant_id=tenant_id,
                    source="message",    # 30-min Redis debounce applies
                )
            except Exception as summary_exc:
                log.warning("concierge_summary_refresh_skipped",
                            conversation_id=conversation_id, error=str(summary_exc))

    except Exception as exc:
        log.error("concierge_draft_failed", message_id=message_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


def _emit_sse(tenant_id: str, event: str, conversation_id: str):
    try:
        import redis, json
        from app.core.config import settings
        r = redis.from_url(settings.REDIS_URL)
        r.publish(f"sse:{tenant_id}", json.dumps({"event": event, "conversation_id": conversation_id}))
    except Exception as e:
        log.warning("sse_publish_failed", error=str(e))
