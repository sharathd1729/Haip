"""
Wrap-up task — generates AI summary + suggested disposition, pushes SSE event.
Uses Gemini Flash (free) or Claude Haiku depending on env config.
"""
import asyncio
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.call import Call, CallDisposition
from app.models.property import Property
from app.models.user import User
from app.adapters.llm import get_llm
from app.core.prompt_versions import stamp
import structlog


def _run_async(coro):
    """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

WRAP_UP_TOOL = {
    "name": "wrap_up_call",
    "description": "Generate a call wrap-up with summary and disposition",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "suggested_disposition": {"type": "string"},
            "next_action": {"type": "string"},
            "follow_up_message": {"type": "string"},  # no union types — Gemini doesn't support ["string","null"]
            "confidence": {"type": "number"},
        },
        "required": ["summary", "suggested_disposition", "next_action"],
    },
}

DISPOSITION_MAP = {
    "hot": CallDisposition.HOT,
    "quoted": CallDisposition.QUOTED,
    "booked": CallDisposition.BOOKED,
    "lost": CallDisposition.LOST,
    "callback": CallDisposition.CALLBACK,
    "no_answer": CallDisposition.NO_ANSWER,
    "voicemail": CallDisposition.VOICEMAIL,
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=15, name="tasks.wrap_up")
def wrap_up(self, call_id: str, tenant_id: str, classification: dict = None, judge_result: dict = None):
    from app.core.database import set_tenant_context
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call:
            return

        prop = db.query(Property).filter_by(id=call.property_id).first() if call.property_id else None
        agent = db.query(User).filter_by(id=call.agent_id).first() if call.agent_id else None

        classification = classification or {}
        judge_result = judge_result or {}

        template = _jinja_env.get_template("wrap_up.jinja")
        system_prompt = template.render(
            property_name=prop.name if prop else "(unknown)",
            agent_name=agent.name if agent else "(unknown)",
            duration_sec=call.duration_seconds,
            direction=call.direction.value if hasattr(call.direction, "value") else call.direction,
            transcript_text=call.ai_summary or "(transcript not available)",
            qa_score=float(call.ai_score) if call.ai_score else None,
            sentiment=classification.get("sentiment", "neutral"),
            intent=classification.get("intent", "unknown"),
            themes=classification.get("themes", []),
            missed_revenue=judge_result.get("missed_revenue", []),
        )

        adapter = get_llm("call_analysis")
        result = _run_async(
            adapter.complete(system_prompt=system_prompt, user_message="Generate the wrap-up.",
                             tools=[WRAP_UP_TOOL])
        )
        wu = result.get("tool_use") or {}

        call.ai_summary = wu.get("summary", call.ai_summary)
        call.ai_next_action = wu.get("next_action")
        disposition_str = wu.get("suggested_disposition", "callback")
        call.ai_disposition = DISPOSITION_MAP.get(disposition_str, CallDisposition.CALLBACK)
        db.commit()

        log.info("wrap_up_done", call_id=call_id, disposition=disposition_str,
                 **stamp("call_wrap_up", model=result.get("model")))

        # Emit SSE event so the frontend cockpit updates in real time
        _emit_sse(tenant_id=tenant_id, event="call_processed", call_id=call_id)

        # Push notification (browser closed / mobile PWA)
        try:
            from app.services.push_service import send_to_tenant
            send_to_tenant(
                db=db,
                tenant_id=tenant_id,
                title="Call summary ready",
                body=call.ai_summary[:80] if call.ai_summary else "AI wrap-up complete.",
                url=f"/dashboard/calls/{call_id}",
                tag="haip-call",
                user_id=call.agent_id or None,
            )
        except Exception as _push_exc:
            log.warning("push_notify_failed", error=str(_push_exc))

        # Fire automation trigger (non-blocking)
        try:
            from app.workers.tasks.automation_engine import fire_trigger
            fire_trigger.apply_async(
                kwargs={
                    "event": "call_completed",
                    "tenant_id": tenant_id,
                    "context": {
                        "call_id": call_id,
                        "disposition": disposition_str,
                    },
                },
                queue="whatsapp",
            )
        except Exception:
            pass

    except Exception as exc:
        log.error("wrap_up_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


def _emit_sse(tenant_id: str, event: str, call_id: str):
    """Publish a message to Redis pub/sub so SSE endpoint can forward to browser."""
    try:
        import redis, json
        from app.core.config import settings
        r = redis.from_url(settings.REDIS_URL)
        r.publish(f"sse:{tenant_id}", json.dumps({"event": event, "call_id": call_id}))
    except Exception as e:
        log.warning("sse_publish_failed", error=str(e))
