"""
Classify task — sentiment, intent, language, themes via LLM.
Uses get_llm("quick_classify") — NVIDIA openai/gpt-oss-20b per the locked
routing table (meta/llama-3.1-8b-instruct reached NIM end-of-life
2026-08-26, HTTP 410). Chains to judge.
"""
import asyncio
import json
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.call import Call
from app.models.guest import Guest
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


def _coerce_bool(value, default: bool = False) -> bool:
    """Seen live under quick_classify's former model (meta/llama-3.1-8b-
    instruct, retired 2026-08-26): a narrower version of CLAUDE.md's
    documented small-model weakness -- is_code_mixed frequently came back
    as the JSON string "true"/"false" instead of a real boolean. Kept as
    cheap defense-in-depth under the new model (openai/gpt-oss-20b) too,
    since nothing guarantees a future NIM model never does this.
    SQLAlchemy's Boolean
    column type raises TypeError on any non-bool value rather than
    coercing it (the literal string "false" is truthy in plain Python
    bool(), so it deliberately refuses to guess) -- this crashed every
    classify run that hit it, retried 3 times, then died, meaning judge/
    wrap_up (and the call's disposition) never ran at all. bool(value)
    alone is NOT safe here for the same reason SQLAlchemy refuses it."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return default

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

# Canonical ToolSpec shape (adapters/llm/tools.py) -- get_llm("quick_classify")
# routes to NVIDIA's OpenAI-compatible endpoint, which needs a different
# wire dialect than this; NvidiaNIMAdapter.complete() renders that
# conversion internally now via to_provider_tools(), so this file (and
# every other task file) only ever declares tools in this one shape.
CLASSIFY_TOOL = {
    "name": "classify_call",
    "description": "Return structured classification of the call including Layer 2 intent and outcome signals",
    "input_schema": {
        "type": "object",
        "properties": {
            # ── Layer 1: Basic classification ────────────────────────────
            "sentiment": {
                "type": "string",
                "enum": ["positive", "neutral", "negative"],
                "description": "Overall guest sentiment during the call",
            },
            "intent": {
                "type": "string",
                "description": "Primary intent: booking_inquiry, price_query, availability_query, experience_interest, complaint, cancellation, general",
            },
            "language": {
                "type": "string",
                "description": "Primary language spoken (en, hi, kn, ta, te, mr, etc.)",
            },
            "is_code_mixed": {
                "type": "boolean",
                "description": "True if guest mixed languages (e.g. Hinglish)",
            },
            "themes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key topics discussed: pricing, availability, amenities, location, upsell, objection, etc.",
            },
            "confidence": {
                "type": "number",
                "description": "Model confidence 0.0–1.0 in the classification",
            },
            # ── Layer 2: Intent & Outcome signals ────────────────────────
            "occasion": {
                "type": "string",
                "description": "Trip occasion if mentioned. One of: honeymoon, anniversary, birthday, corporate, family, solo, wedding, other. Empty string if not mentioned.",
            },
            "budget_signal": {
                "type": "string",
                "description": "Guest's reaction to price if any price was discussed. E.g. 'That\\'s high', 'Okay works for us', 'Can you do better?', 'Seems reasonable'. Empty string if price not discussed.",
            },
            "decision_stage": {
                "type": "string",
                "description": "Where the guest is in their decision journey. One of: first_inquiry, comparing, ready_to_book. Empty string if unclear.",
            },
            "competitor_mentioned": {
                "type": "string",
                "description": "Name of any competitor or alternative property mentioned (e.g. StayVista, Airbnb, another villa name). Empty string if none.",
            },
            "conversion_probability": {
                "type": "number",
                "description": "Estimated probability (0–100) that this guest will book based on their engagement, intent signals, and decision stage.",
            },
            "lost_reason": {
                "type": "string",
                "description": "If the call ended without converting, the likely reason. One of: price, dates_unavailable, still_comparing, no_response, wrong_property, other. Empty string if not lost.",
            },
            "guest_name": {
                "type": "string",
                "description": "The guest/caller's first name if they state it themselves during the call (e.g. \"This is Priya calling\", \"Meera here\"). Do NOT use the agent's name. Empty string if the guest never states their name.",
            },
        },
        "required": ["sentiment", "intent", "language", "is_code_mixed", "themes", "confidence",
                     "occasion", "budget_signal", "decision_stage", "competitor_mentioned",
                     "conversion_probability", "lost_reason", "guest_name"],
    },
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="tasks.classify")
def classify(self, call_id: str, tenant_id: str):
    from app.workers.tasks.judge import judge

    from app.core.database import set_tenant_context
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
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

        adapter = get_llm("quick_classify")
        result = _run_async(
            adapter.complete(
                system_prompt=system_prompt,
                user_message="Classify this call.",
                tools=[CLASSIFY_TOOL],
            )
        )

        classification = result.get("tool_use") or {}

        # ── Update call with Layer 1 + Layer 2 classification results ────────
        call.detected_language = classification.get("language", call.detected_language)
        call.is_code_mixed = _coerce_bool(classification.get("is_code_mixed"), False)

        # Layer 2: Intent & Outcome
        occasion = classification.get("occasion", "")
        if occasion:
            call.occasion = occasion

        budget_signal = classification.get("budget_signal", "")
        if budget_signal:
            call.budget_signal = budget_signal

        decision_stage = classification.get("decision_stage", "")
        if decision_stage:
            call.decision_stage = decision_stage

        competitor = classification.get("competitor_mentioned", "")
        if competitor:
            call.competitor_mentioned = competitor

        conv_prob = classification.get("conversion_probability")
        if conv_prob is not None:
            call.conversion_probability = int(conv_prob)

        lost_reason = classification.get("lost_reason", "")
        if lost_reason:
            call.lost_reason = lost_reason

        # Detect the guest's spoken name and backfill the Guest record --
        # only when currently unnamed, so a name confidently entered
        # elsewhere is never clobbered. Matches the same guard used in
        # guest_service.upsert_by_phone().
        guest_name = (classification.get("guest_name") or "").strip()
        # Guard against the model echoing a non-name placeholder it saw
        # in the transcript/agent notes (e.g. "caller unknown") -- seen
        # live producing Guest.name == "Unknown" (not our own placeholder
        # string, so the guard above didn't already catch it).
        if guest_name.lower() in {"unknown", "unnamed", "n/a", "na", "none", "unidentified"}:
            guest_name = ""
        if guest_name and call.guest_id:
            guest = db.query(Guest).filter_by(id=call.guest_id, tenant_id=tenant_id).first()
            if guest and (not guest.name or guest.name == "Unknown Guest"):
                guest.name = guest_name
                log.info("guest_name_detected_from_call", call_id=call_id, guest_id=guest.id)

        db.commit()

        log.info(
            "classify_done",
            call_id=call_id,
            sentiment=classification.get("sentiment"),
            occasion=occasion or None,
            conversion_probability=conv_prob,
            decision_stage=decision_stage or None,
            **stamp("call_classify"),
        )

        # Chain to judge (best-effort — fails gracefully if broker is down)
        try:
            judge.delay(call_id=call_id, tenant_id=tenant_id, classification=classification)
        except Exception as chain_exc:
            log.warning("classify_chain_judge_skipped", call_id=call_id, error=str(chain_exc))

        # Leads360: trigger AI summary refresh for the linked inquiry (no debounce for calls)
        if call.inquiry_id:
            try:
                from app.services.leads_service import trigger_summary_refresh
                trigger_summary_refresh(
                    db=db,
                    inquiry_id=str(call.inquiry_id),
                    tenant_id=tenant_id,
                    source="call",
                )
            except Exception as summary_exc:
                log.warning("classify_summary_refresh_skipped", call_id=call_id,
                            error=str(summary_exc))

    except Exception as exc:
        log.error("classify_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
