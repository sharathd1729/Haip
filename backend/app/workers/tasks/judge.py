"""
Judge task — QA scoring via LLM rubric. Uses get_llm("call_scoring")
(NVIDIA nemotron-super-49b). Confidence < 0.78 escalates to
get_llm("deep_reason") (NVIDIA nemotron-3-ultra-550b) for a re-judge.
Chains to wrap_up.
"""
import asyncio
import json
import uuid


def _run_async(coro):
    """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.call import Call, CallDisposition
from app.models.transcript import Transcript
from app.models.score import Rubric, CallScore
from app.models.property import Property
from app.models.user import User
from app.adapters.llm import get_llm
from app.core.prompt_versions import stamp
from app.services.transcription_service import redact_pii
from app.services.qa_service import get_default_rubric, store_score
import structlog

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

CONFIDENCE_THRESHOLD = 0.78

# Canonical ToolSpec shape (adapters/llm/tools.py) — see note in
# classify.py's CLASSIFY_TOOL.
JUDGE_TOOL = {
    "name": "judge_call",
    "description": "Return structured QA scoring of the call",
    "input_schema": {
        "type": "object",
        "properties": {
            "criterion_scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":        {"type": "string"},
                        "score":     {"type": "number"},
                        "evidence":  {"type": "string"},  # plain string, no nested arrays
                    },
                    "required": ["id", "score", "evidence"],
                },
            },
            "has_auto_fail":      {"type": "boolean"},
            "sentiment":          {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "intent":             {"type": "string"},
            "language":           {"type": "string"},
            "themes":             {"type": "array", "items": {"type": "string"}},
            "confidence":         {"type": "number"},
            "agent_strengths":    {"type": "string"},
            "agent_growth_areas": {"type": "string"},
        },
        "required": ["criterion_scores", "confidence", "sentiment"],
    },
}

DEFAULT_RUBRIC_CRITERIA = [
    {"id": "greeting", "name": "Warm greeting + brand intro", "weight": 8, "method": "YES_NO", "description": "Agent greeted warmly and introduced the brand"},
    {"id": "discovery", "name": "Discovery quality", "weight": 12, "method": "ZERO_THREE", "description": "Asked about occasion, group size, dates, budget"},
    {"id": "expertise", "name": "Property/itinerary expertise", "weight": 12, "method": "ZERO_THREE", "description": "Demonstrated knowledge of properties and experiences"},
    {"id": "pricing", "name": "Pricing transparency", "weight": 10, "method": "YES_NO", "description": "Quoted pricing honestly and clearly"},
    {"id": "empathy", "name": "Empathy on luxury cues", "weight": 10, "method": "ZERO_THREE", "description": "Responded to emotional cues with warmth"},
    {"id": "objection", "name": "Objection handling", "weight": 10, "method": "ZERO_THREE", "description": "Handled price/availability objections professionally"},
    {"id": "next_step", "name": "Clear next step", "weight": 12, "method": "YES_NO", "description": "Committed to a specific next step"},
    {"id": "close", "name": "Close attempt", "weight": 12, "method": "YES_NO", "description": "Attempted to close or book"},
    {"id": "pii_discipline", "name": "No PII leakage", "weight": 8, "method": "AUTO_FAIL", "description": "Did not share other guest PII"},
    {"id": "professionalism", "name": "Professional tone", "weight": 6, "method": "ZERO_THREE", "description": "Maintained professional and courteous tone throughout"},
]


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="tasks.judge")
def judge(self, call_id: str, tenant_id: str, classification: dict = None):
    from app.workers.tasks.wrap_up import wrap_up

    from app.core.database import set_tenant_context
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        transcript = db.query(Transcript).filter_by(call_id=call_id, tenant_id=tenant_id).first()
        if not call or not transcript:
            log.error("judge_missing_data", call_id=call_id)
            return

        call.ai_score_status = "processing"
        db.commit()

        # Get or create default rubric
        rubric = get_default_rubric(db, tenant_id)
        if not rubric:
            rubric = Rubric(
                id=str(uuid.uuid4()), tenant_id=tenant_id,
                name="hospitality_v1", version="1.0",
                criteria=DEFAULT_RUBRIC_CRITERIA, is_default=True, is_active=True,
            )
            db.add(rubric); db.flush()

        # Build transcript text (PII-redacted)
        turns = json.loads(transcript.turns or "[]")
        transcript_text = redact_pii(
            "\n".join(f"[{t['t0']:.1f}s] {t['speaker'].upper()}: {t['text']}" for t in turns)
        )

        prop = db.query(Property).filter_by(id=call.property_id).first() if call.property_id else None
        agent = db.query(User).filter_by(id=call.agent_id).first() if call.agent_id else None

        # Build judge prompt
        rubric_obj = type("R", (), {
            "name": rubric.name, "version": rubric.version,
            "vertical": "luxury", "criteria": rubric.criteria,
        })()
        prop_obj = type("P", (), {"name": prop.name if prop else "(unknown)", "type": prop.type if prop else "villa"})()
        agent_obj = type("A", (), {"full_name": agent.name if agent else "(unknown)", "role": agent.role.value if agent and hasattr(agent.role, "value") else "concierge"})()

        template = _jinja_env.get_template("judge.jinja")
        system_prompt = template.render(
            rubric=rubric_obj, property=prop_obj, agent=agent_obj,
            duration_sec=call.duration_seconds,
            direction=call.direction.value if hasattr(call.direction, "value") else call.direction,
            language=transcript.language or "en",
            is_code_mixed=call.is_code_mixed,
            transcript_turns_compact=transcript_text,
        )

        adapter = get_llm("call_scoring")

        # First pass: the task-routed model for call_scoring.
        result_fast = _run_async(
            adapter.complete(system_prompt=system_prompt, user_message="Score this call.",
                             tools=[JUDGE_TOOL])
        )
        judge_result = result_fast.get("tool_use") or {}
        model_used = result_fast.get("model", "call_scoring")

        # Escalate to the stronger deep_reason model if confidence < threshold
        if judge_result.get("confidence", 1.0) < CONFIDENCE_THRESHOLD:
            log.info("judge_escalating", call_id=call_id, confidence=judge_result.get("confidence"))
            strong_adapter = get_llm("deep_reason")
            result_strong = _run_async(
                strong_adapter.complete(system_prompt=system_prompt, user_message="Score this call.",
                                        tools=[JUDGE_TOOL])
            )
            judge_result = result_strong.get("tool_use") or judge_result
            model_used = result_strong.get("model", "deep_reason") + "_review"

        judge_result["model_used"] = model_used
        score = store_score(db, call_id=call_id, tenant_id=tenant_id, rubric_id=rubric.id, result=judge_result)

        # Update call summary fields
        call.ai_score = float(score.percentage)
        call.ai_score_status = "done"
        db.commit()

        log.info("judge_done", call_id=call_id, score=float(score.percentage),
                 **stamp("call_judge", model=model_used))

        # Chain to wrap_up (best-effort — fails gracefully if broker is down)
        try:
            wrap_up.delay(call_id=call_id, tenant_id=tenant_id, classification=classification or {}, judge_result=judge_result)
        except Exception as chain_exc:
            log.warning("judge_chain_wrap_up_skipped", call_id=call_id, error=str(chain_exc))

    except Exception as exc:
        try:
            call.ai_score_status = "failed"; db.commit()
        except Exception:
            pass
        log.error("judge_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
