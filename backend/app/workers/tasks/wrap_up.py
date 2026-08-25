"""
Wrap-up task — generates AI summary + suggested disposition, pushes SSE event.
Uses Gemini Flash (free) or Claude Haiku depending on env config.
"""
import asyncio
import json
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

        template = _jinja_env.get_template("wrap_up.jinja")
        system_prompt = template.render(
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
        call.ai_next_action = wu.get("next_action")
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
