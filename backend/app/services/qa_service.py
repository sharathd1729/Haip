"""QA scoring service."""
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from app.models.score import Rubric, CallScore
import structlog

log = structlog.get_logger()


def get_default_rubric(db: Session, tenant_id: str) -> Optional[Rubric]:
    return (
        db.query(Rubric)
        .filter_by(tenant_id=tenant_id, is_default=True, is_active=True)
        .first()
    )


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


def ensure_default_rubric(db: Session, tenant_id: str) -> Rubric:
    """The tenant's default rubric, created from DEFAULT_RUBRIC_CRITERIA the first time a call is scored."""
    rubric = get_default_rubric(db, tenant_id)
    if not rubric:
        rubric = Rubric(id=str(uuid.uuid4()), tenant_id=tenant_id, name="hospitality_v1", version="1.0",
                        criteria=DEFAULT_RUBRIC_CRITERIA, is_default=True, is_active=True)
        db.add(rubric)
        db.flush()
    return rubric


def override_score(
    db: Session,
    tenant_id: str,
    score_id: str,
    criterion_scores: list,
    reason: str,
    overridden_by: str,
) -> CallScore:
    score = db.query(CallScore).filter_by(id=score_id, tenant_id=tenant_id).first()
    if not score:
        raise ValueError(f"Score {score_id} not found")

    score.is_overridden = True
    score.override_scores = criterion_scores
    score.override_reason = reason
    score.overridden_by = overridden_by
    from datetime import datetime, timezone
    score.overridden_at = datetime.now(timezone.utc).isoformat()

    log.info("score_overridden", score_id=score_id, overridden_by=overridden_by)
    return score


def compute_score(rubric_criteria: list, criterion_scores: list) -> tuple[float, float, float]:
    """(total, max_possible, percentage) of criterion scores against a rubric's weights.
    YES_NO / AUTO_FAIL are worth their full weight (0 or weight); ZERO_THREE is weight * score/3."""
    weight_map = {c["id"]: c.get("weight", 10) for c in rubric_criteria} if rubric_criteria else {}
    method_map = {c["id"]: c.get("method", "YES_NO") for c in rubric_criteria or []}
    total = 0.0
    max_possible = 0.0
    for c in criterion_scores:
        cid = c.get("id", "")
        raw_score = float(c.get("score", 0))
        weight = weight_map.get(cid, 10)
        max_possible += weight
        if method_map.get(cid, "YES_NO") == "ZERO_THREE":
            total += weight * (raw_score / 3.0)
        else:  # YES_NO, AUTO_FAIL
            total += weight * raw_score

    # Fallback when no rubric criteria (flat sum)
    if not rubric_criteria:
        total = sum(float(c.get("score", 0)) for c in criterion_scores)
        max_possible = len(criterion_scores) * 10

    percentage = (total / max_possible * 100) if max_possible else 0
    return total, max_possible, percentage


def store_score(db: Session, call_id: str, tenant_id: str, rubric_id: str, result: dict,
                analysis_version: Optional[str] = None) -> CallScore:
    """Persist a scoring result to call_scores. With an analysis_version the row is ONE per (call, version): a retry
    or a recovery run updates it instead of adding another (a score a person overrode is left as it is)."""
    rubric = db.query(Rubric).filter_by(id=rubric_id, tenant_id=tenant_id).first()
    rubric_criteria = rubric.criteria if rubric else []
    criterion_scores = result.get("criterion_scores", [])
    total, max_possible, percentage = compute_score(rubric_criteria, criterion_scores)

    score = None
    if analysis_version:
        score = (db.query(CallScore)
                 .filter_by(tenant_id=tenant_id, call_id=call_id, analysis_version=analysis_version).first())
        if score is not None and score.is_overridden:
            return score
    if score is None:
        score = CallScore(id=str(uuid.uuid4()), tenant_id=tenant_id, call_id=call_id,
                          analysis_version=analysis_version)
        db.add(score)
    score.rubric_id = rubric_id
    score.rubric_snapshot = rubric_criteria or {}
    score.total_score = total
    score.max_score = max_possible
    score.percentage = percentage
    score.has_auto_fail = bool(result.get("has_auto_fail", False))
    score.criterion_scores = criterion_scores
    score.model_used = (result.get("model_used") or "unknown")[:50]
    score.ai_confidence = result.get("confidence")
    db.flush()
    return score
