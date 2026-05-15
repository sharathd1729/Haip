"""
Classify task — sentiment, intent, language, themes via LLM.
Uses Gemini Flash (free) or Claude Haiku depending on env config.
Chains to judge.
"""
import asyncio
import json
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.property import Property
from app.models.user import User
from app.adapters.llm import get_llm_adapter
from app.services.transcription_service import redact_pii
import structlog


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

CLASSIFY_TOOL = {
    "name": "classify_call",
    "description": "Return structured classification of the call",
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "intent": {"type": "string"},
            "language": {"type": "string"},
            "is_code_mixed": {"type": "boolean"},
            "themes": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["sentiment", "intent", "language", "is_code_mixed", "themes", "confidence"],
    },
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="tasks.classify")
def classify(self, call_id: str, tenant_id: str):
    from app.workers.tasks.judge import judge

    db = SessionLocal()
    try:
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        transcript = db.query(Transcript).filter_by(call_id=call_id, tenant_id=tenant_id).first()

        if not call or not transcript:
            log.error("classify_missing_data", call_id=call_id)
            return

        # Redact PII before sending to Claude
        turns = json.loads(transcript.turns or "[]")
        transcript_text = redact_pii(
            "\n".join(f"[{t['t0']:.1f}s] {t['speaker'].upper()}: {t['text']}" for t in turns)
        )

        prop = db.query(Property).filter_by(id=call.property_id).first() if call.property_id else None
        agent = db.query(User).filter_by(id=call.agent_id).first() if call.agent_id else None

        template = _jinja_env.get_template("classify.jinja")
        system_prompt = template.render(
            property_name=prop.name if prop else "(unknown)",
            direction=call.direction.value if hasattr(call.direction, "value") else call.direction,
            duration_sec=call.duration_seconds,
            agent_name=agent.name if agent else "(unknown)",
            transcript_text=transcript_text,
        )

        adapter = get_llm_adapter()
        result = _run_async(
            adapter.complete(
                system_prompt=system_prompt,
                user_message="Classify this call.",
                model="claude-haiku-4-5-20251001",   # Gemini maps this → Flash
                tools=[CLASSIFY_TOOL],
            )
        )

        classification = result.get("tool_use") or {}

        # Update call with classification results
        call.detected_language = classification.get("language", call.detected_language)
        call.is_code_mixed = classification.get("is_code_mixed", False)
        db.commit()

        log.info("classify_done", call_id=call_id, sentiment=classification.get("sentiment"))

        # Chain to judge (best-effort — fails gracefully if broker is down)
        try:
            judge.delay(call_id=call_id, tenant_id=tenant_id, classification=classification)
        except Exception as chain_exc:
            log.warning("classify_chain_judge_skipped", call_id=call_id, error=str(chain_exc))

    except Exception as exc:
        log.error("classify_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
