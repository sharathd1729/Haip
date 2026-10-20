"""
AI QA scoring pipeline: transcript → Claude Haiku/Sonnet → CallScore.
Uses Haiku by default; escalates to Sonnet when confidence < 0.78.
"""
import json
import uuid
from typing import Optional
from anthropic import Anthropic
from celery import shared_task
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.call import Call, CallDisposition
from app.models.score import CallScore, Rubric
from app.workers.celery_app import celery_app
import structlog

log = structlog.get_logger()

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

DEFAULT_RUBRIC = {
    "criteria": [
        {"id": "greeting", "name": "Warm greeting + brand intro", "weight": 8, "method": "yes_no"},
        {"id": "discovery", "name": "Discovery quality (occasion, group, budget)", "weight": 12, "method": "zero_three"},
        {"id": "expertise", "name": "Itinerary / property expertise", "weight": 12, "method": "zero_three"},
        {"id": "pricing", "name": "Pricing transparency", "weight": 10, "method": "yes_no"},
        {"id": "empathy", "name": "Empathy on luxury cues", "weight": 10, "method": "zero_three"},
        {"id": "objection", "name": "Objection handling", "weight": 10, "method": "zero_three"},
        {"id": "next_step", "name": "Clear next step committed", "weight": 12, "method": "yes_no"},
        {"id": "close", "name": "Close + commitment attempt", "weight": 12, "method": "yes_no"},
        {"id": "pii_discipline", "name": "No PII leakage", "weight": 8, "method": "auto_fail"},
        {"id": "professionalism", "name": "Professional tone throughout", "weight": 6, "method": "zero_three"},
    ]
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="ai_scoring.score_call")
def score_call(self, call_id: str, tenant_id: str):
    """Score call transcript using Claude Haiku (escalate to Sonnet if needed)."""
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call:
            log.error("call_not_found", call_id=call_id)
            return

        # Prefer the canonical Transcript table; fall back to legacy inline JSON
        from app.models.transcript import Transcript as TranscriptModel
        transcript_row = db.query(TranscriptModel).filter_by(call_id=call_id, tenant_id=tenant_id).first()
        if transcript_row:
            import json as _json
            turns_list = _json.loads(transcript_row.turns or "[]") if isinstance(transcript_row.turns, str) else (transcript_row.turns or [])
        elif call.transcript_json:
            turns_list = call.transcript_json
        else:
            log.error("transcript_not_found", call_id=call_id)
            return

        if not turns_list:
            log.error("transcript_empty", call_id=call_id)
            return

        call.ai_score_status = "processing"
        db.commit()

        # Get or create rubric for tenant
        rubric = db.query(Rubric).filter_by(tenant_id=tenant_id, is_default=True, is_active=True).first()
        if not rubric:
            rubric = Rubric(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name="Default Rubric",
                criteria=DEFAULT_RUBRIC["criteria"],
                is_default=True,
                is_active=True,
            )
            db.add(rubric)
            db.flush()

        transcript_text = _format_transcript(turns_list)

        # First pass: Haiku
        result = _call_llm_judge(transcript_text, rubric.criteria, model="claude-haiku-4-5-20251001")

        # Escalate to Sonnet if confidence is low
        if result.get("overall_confidence", 1.0) < 0.78:
            log.info("escalating_to_sonnet", call_id=call_id, confidence=result.get("overall_confidence"))
            result = _call_llm_judge(transcript_text, rubric.criteria, model="claude-sonnet-4-6")
            model_used = "claude-sonnet-4-6"
        else:
            model_used = "claude-haiku-4-5-20251001"

        # Compute total score
        total_score, max_score = _compute_score(result["criteria_scores"], rubric.criteria)
        percentage = (total_score / max_score * 100) if max_score > 0 else 0
        has_auto_fail = any(
            cs.get("score") == 0 and _get_criterion(rubric.criteria, cs["criterion_id"]).get("method") == "auto_fail"
            for cs in result["criteria_scores"]
        )

        call_score = CallScore(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            call_id=call_id,
            rubric_id=rubric.id,
            rubric_snapshot=rubric.criteria,
            total_score=total_score,
            max_score=max_score,
            percentage=round(percentage, 2),
            has_auto_fail=has_auto_fail,
            criterion_scores=result["criteria_scores"],
            model_used=model_used,
            ai_confidence=result.get("overall_confidence"),
        )
        db.add(call_score)

        # Update call
        call.ai_score = round(percentage, 2)
        call.ai_summary = result.get("summary", "")
        call.ai_disposition = _map_disposition(result.get("disposition", ""))
        call.ai_next_action = result.get("next_action", "")
        call.ai_score_status = "done"

        from app.services.next_action_service import derive_recommended_action
        action_type, action_target = derive_recommended_action(db, call)
        call.recommended_action_type = action_type
        call.recommended_action_target_id = action_target

        # Estimate LLM cost
        call.llm_cost_usd = 0.0001 if model_used == "claude-haiku-4-5-20251001" else 0.003

        db.commit()
        log.info("scoring_complete", call_id=call_id, score=percentage, model=model_used)

        # Lead workflows: a call that turns out to be unanswered (voicemail, no answer) gets its missed-call / no-answer
        # WhatsApp now if ingest could not tell (the run's unique key makes a second trigger a no-op).
        try:
            from app.services.lead_playbook_engine import playbook_for_call
            if playbook_for_call(call):
                from app.workers.tasks.lead_playbooks import queue_on_call
                queue_on_call(call.tenant_id, call.id, countdown=5)
        except Exception as _pb_exc:  # noqa: BLE001
            log.warning("playbook_requeue_failed", call_id=call.id, error=str(_pb_exc)[:200])

    except Exception as exc:
        if db:
            try:
                call_obj = db.query(Call).filter_by(id=call_id).first()
                if call_obj:
                    call_obj.ai_score_status = "failed"
                    db.commit()
            except Exception:
                pass
        log.error("scoring_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


def _call_llm_judge(transcript: str, criteria: list, model: str) -> dict:
    criteria_json = json.dumps(criteria, indent=2)
    prompt = f"""You are an expert hospitality QA analyst. Score this call transcript against each criterion.

CRITERIA:
{criteria_json}

TRANSCRIPT:
{transcript}

Respond with valid JSON only:
{{
  "summary": "2-3 sentence summary of the call",
  "disposition": "hot|quoted|booked|lost|callback|no_answer",
  "next_action": "Specific next step the agent should take",
  "overall_confidence": 0.0-1.0,
  "criteria_scores": [
    {{
      "criterion_id": "greeting",
      "score": 0 or 1 (for yes_no), 0-3 (for zero_three), 0 (auto_fail means failed),
      "confidence": 0.0-1.0,
      "evidence_span": "direct quote from transcript supporting this score",
      "reasoning": "1 sentence explanation"
    }}
  ]
}}"""

    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = msg.content[0].text.strip()
    # Strip markdown code blocks if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _format_transcript(turns: list) -> str:
    lines = []
    for t in (turns or []):
        speaker = t.get("speaker", "unknown").upper()
        text = t.get("text", "")
        start = t.get("start", 0)
        lines.append(f"[{start:.1f}s] {speaker}: {text}")
    return "\n".join(lines)


def _compute_score(criteria_scores: list, rubric_criteria: list) -> tuple:
    total = 0.0
    max_total = 0.0
    for cs in criteria_scores:
        criterion = _get_criterion(rubric_criteria, cs["criterion_id"])
        if not criterion:
            continue
        weight = criterion.get("weight", 10)
        method = criterion.get("method", "yes_no")
        score = cs.get("score", 0)

        if method == "yes_no":
            total += weight * score  # score is 0 or 1
            max_total += weight
        elif method == "zero_three":
            total += weight * (score / 3)
            max_total += weight
        elif method == "auto_fail":
            total += weight * score
            max_total += weight

    return total, max_total


def _get_criterion(criteria: list, criterion_id: str) -> dict:
    return next((c for c in criteria if c["id"] == criterion_id), {})


def _map_disposition(raw: str) -> Optional[CallDisposition]:
    mapping = {
        "hot": CallDisposition.HOT,
        "quoted": CallDisposition.QUOTED,
        "booked": CallDisposition.BOOKED,
        "lost": CallDisposition.LOST,
        "callback": CallDisposition.CALLBACK,
        "no_answer": CallDisposition.NO_ANSWER,
        "voicemail": CallDisposition.VOICEMAIL,
    }
    # A missing/unrecognized disposition must never default to CALLBACK --
    # that's an ANSWERED value (call_status_service.py's ANSWERED set), so
    # "the model gave us nothing usable" was silently reading as "the guest
    # was answered and asked for a callback." None lets is_missed_call()
    # fall through to the real dial_status/duration signals instead of a
    # wrong, answered-implying guess.
    return mapping.get((raw or "").strip().lower())
