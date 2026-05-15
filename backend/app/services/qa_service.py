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


def store_score(db: Session, call_id: str, tenant_id: str, rubric_id: str, result: dict) -> CallScore:
    """Persist a judge result to call_scores table."""
    import json
    rubric = db.query(Rubric).filter_by(id=rubric_id).first()
    rubric_snapshot = rubric.criteria if rubric else {}

    criterion_scores = result.get("criterion_scores", [])

    # Build a weight lookup from rubric criteria
    rubric_criteria = rubric.criteria if rubric else []
    weight_map = {c["id"]: c.get("weight", 10) for c in rubric_criteria} if rubric_criteria else {}

    # Calculate weighted score
    # YES_NO criteria are worth their full weight (0 or weight)
    # ZERO_THREE criteria are worth weight * score/3
    method_map = {c["id"]: c.get("method", "YES_NO") for c in rubric_criteria}
    total = 0.0
    max_possible = 0.0
    for c in criterion_scores:
        cid = c.get("id", "")
        raw_score = float(c.get("score", 0))
        method = method_map.get(cid, "YES_NO")
        weight = weight_map.get(cid, 10)
        max_possible += weight
        if method == "ZERO_THREE":
            total += weight * (raw_score / 3.0)
        else:  # YES_NO, AUTO_FAIL
            total += weight * raw_score

    # Fallback when no rubric criteria (flat sum)
    if not rubric_criteria:
        total = sum(float(c.get("score", 0)) for c in criterion_scores)
        max_possible = len(criterion_scores) * 10

    percentage = (total / max_possible * 100) if max_possible else 0

    score = CallScore(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_id=call_id,
        rubric_id=rubric_id,
        rubric_snapshot=rubric_snapshot,
        total_score=total,
        max_score=max_possible,
        percentage=percentage,
        has_auto_fail=result.get("has_auto_fail", False),
        criterion_scores=criterion_scores,
        model_used=result.get("model_used", "claude-haiku"),
        ai_confidence=result.get("confidence"),
    )
    db.add(score)
    db.flush()
    return score
