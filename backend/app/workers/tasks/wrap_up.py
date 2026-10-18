"""
Wrap-up task — generates AI summary + suggested disposition, pushes SSE event.
Uses Gemini Flash (free) or Claude Haiku depending on env config.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.call import Call, CallDisposition
from app.models.transcript import Transcript
from app.models.property import Property
from app.models.user import User
from app.adapters.llm import get_llm
from app.core.prompt_versions import stamp
from app.services.transcription_service import redact_pii
import structlog


def _run_async(coro):
    """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

log = structlog.get_logger()

# How long before a "guest asked for a callback" reminder is "due" on My
# Day -- shorter than the outbound-no-answer reminder (call_ingest.py's
# _CALLBACK_REMINDER_WINDOW): the guest explicitly asked, this is higher
# intent than an unanswered dial-out.
_CALLBACK_REQUESTED_WINDOW = timedelta(hours=1)


def _maybe_create_callback_requested_task(db, tenant_id: str, call: Call) -> None:
    """The AI wrap-up already detects when a guest asked to be called back
    (CallDisposition.CALLBACK) -- confirmed live gap (Ratha, Sep 2026,
    "autopilot" pass): call_status_service.py correctly classifies this as
    ANSWERED (a real conversation happened), so it's excluded from the
    missed-call queue by definition, and nothing else ever read it. Turns
    that already-captured signal into an actual reminder. Same shape as
    concierge_draft.py's _maybe_create_price_handoff/_maybe_alert_phone_decline
    and call_ingest.py's _maybe_create_callback_task: dedup on an open task
    with a matching title, real due_date, a push alert."""
    from app.models.guest import Guest
    from app.models.task import Task

    if not call.guest_id:
        return

    existing = (
        db.query(Task)
        .filter_by(tenant_id=tenant_id, guest_id=call.guest_id, is_done=False)
        .filter(Task.title.ilike("Callback requested — %"))
        .first()
    )
    if existing:
        return

    guest = db.query(Guest).filter_by(id=call.guest_id, tenant_id=tenant_id).first()
    guest_label = (getattr(guest, "name", None) or "").strip() or "this lead"
    task = Task(
        tenant_id=tenant_id,
        title=f"Callback requested — {guest_label}",
        priority="high",
        guest_id=call.guest_id,
        inquiry_id=call.inquiry_id,
        assigned_to=call.agent_id,
        due_date=datetime.now(timezone.utc) + _CALLBACK_REQUESTED_WINDOW,
    )
    db.add(task)
    db.commit()
    log.info("callback_requested_task_created", tenant_id=tenant_id, call_id=call.id, task_id=task.id)

    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(
            db, tenant_id,
            title="Guest asked for a callback",
            body=f"{guest_label} asked to be called back. A reminder has been added.",
            url=f"/dashboard/calls?call={call.id}",
            user_id=call.agent_id or None,
        )
    except Exception as exc:
        log.warning("callback_requested_task_push_failed", tenant_id=tenant_id, error=str(exc))


PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

# Canonical ToolSpec shape (adapters/llm/tools.py) — get_llm() routes
# call_analysis to NVIDIA today, but this no longer hard-codes that
# provider's wire dialect; each adapter renders it internally.
WRAP_UP_TOOL = {
    "name": "wrap_up_call",
    "description": "Generate a call wrap-up with summary and disposition",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "suggested_disposition": {"type": "string"},
            "next_action": {"type": "string"},
            "follow_up_message": {"type": "string"},  # no union types
            "confidence": {"type": "number"},
            # v5 actionable read (services/ai_actionable.py cleans it; all optional so an older-shaped answer still works)
            "outcome": {"type": "string"},
            "decline_reason": {"type": "string"},
            "decline_quote": {"type": "string"},
            "next_best_action": {"type": "object", "properties": {
                "action": {"type": "string"}, "owner": {"type": "string"}, "channel": {"type": "string"},
                "deadline": {"type": "string"}, "why": {"type": "string"}}},
            "blocking_objection": {"type": "object", "properties": {
                "objection": {"type": "string"}, "counter": {"type": "string"}}},
            "missed_revenue": {"type": "array", "items": {"type": "object", "properties": {
                "kind": {"type": "string"}, "what": {"type": "string"}, "est_inr": {"type": "number"},
                "grounded": {"type": "boolean"}, "evidence": {"type": "string"}}}},
            "temperature": {"type": "object", "properties": {"value": {"type": "string"}, "reason": {"type": "string"}}},
            "haip_updates": {"type": "array", "items": {"type": "object", "properties": {
                "field": {"type": "string"}, "value": {"type": "string"}, "why": {"type": "string"}}}},
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

        # Real, load-bearing bug: this used to read call.ai_summary as
        # "the transcript" -- but call.ai_summary is never set by anything
        # except wrap_up's own previous run (or ai_scoring.py's dead
        # pipeline). On a call's first-ever wrap_up it was None, rendering
        # the literal string "(transcript not available)"; on any re-run
        # (e.g. a backfill) it fed the model its own prior, low-information
        # summary instead of the real conversation -- a self-reinforcing
        # genericization loop, same shape as the earlier-fixed WhatsApp
        # context-pollution bug. wrap_up has never had real transcript
        # content, for any call, ever. Query the real Transcript directly,
        # same construction judge.py already uses correctly.
        transcript = db.query(Transcript).filter_by(call_id=call_id, tenant_id=tenant_id).first()
        if transcript:
            turns = json.loads(transcript.turns or "[]")
            transcript_text = redact_pii(
                "\n".join(f"[{t['t0']:.1f}s] {t['speaker'].upper()}: {t['text']}" for t in turns)
            ) or "(transcript not available)"
        else:
            transcript_text = "(transcript not available)"

        prop = db.query(Property).filter_by(id=call.property_id).first() if call.property_id else None
        agent = db.query(User).filter_by(id=call.agent_id).first() if call.agent_id else None

        classification = classification or {}
        judge_result = judge_result or {}

        from app.models.guest import Guest
        from app.services import ai_actionable
        guest = db.query(Guest).filter_by(id=call.guest_id, tenant_id=tenant_id).first() if call.guest_id else None

        template = _jinja_env.get_template("wrap_up.jinja")
        system_prompt = template.render(
            call_date=call.created_at.date().isoformat() if call.created_at else None,
            guest_name=(guest.name if guest and guest.name else None),
            actionable_spec=ai_actionable.PROMPT_SPEC.rstrip(),
            actionable_rules=ai_actionable.PROMPT_RULES,
            property_name=prop.name if prop else "(unknown)",
            agent_name=agent.name if agent else "(unknown)",
            duration_sec=call.duration_seconds,
            direction=call.direction.value if hasattr(call.direction, "value") else call.direction,
            transcript_text=transcript_text,
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
        insights = ai_actionable.clean_call_insights(wu)
        call.ai_insights = insights
        call.ai_next_action = wu.get("next_action") or ai_actionable.next_action_text((insights or {}).get("next_best_action"))
        # A missing/unrecognized disposition must never default to CALLBACK
        # -- that's an ANSWERED value (call_status_service.py's ANSWERED
        # set), so "the model gave us nothing usable" was silently reading
        # as "the guest was answered and asked for a callback." Confirmed
        # live: a pure-greeting, nobody-picked-up call ended up with
        # ai_disposition=CALLBACK and was never flagged missed. None here
        # lets is_missed_call() fall through to the real dial_status/
        # duration signals instead of a wrong, answered-implying guess.
        disposition_str = (wu.get("suggested_disposition") or "").strip().lower()
        call.ai_disposition = DISPOSITION_MAP.get(disposition_str)
        db.commit()

        if call.ai_disposition == CallDisposition.CALLBACK:
            _maybe_create_callback_requested_task(db, tenant_id, call)

        log.info("wrap_up_done", call_id=call_id, disposition=disposition_str,
                 **stamp("call_wrap_up", model=result.get("model")))

        # Lead autopilot: the call is fully analysed now (disposition + outcome), so re-read the lead's stage.
        try:
            from app.services import lead_autopilot_service
            lead_autopilot_service.queue_evaluation(
                call.inquiry_id or lead_autopilot_service.open_inquiry_for_guest(db, tenant_id, call.guest_id),
                tenant_id, trigger="call")
        except Exception as _ap_exc:
            log.warning("wrap_up_autopilot_enqueue_failed", call_id=call_id, error=str(_ap_exc)[:200])

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
