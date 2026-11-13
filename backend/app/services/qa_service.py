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


class OverrideError(ValueError):
    """A correction the person has to fix; the message is safe to show."""


def override_score(
    db: Session,
    tenant_id: str,
    score_id: str,
    criterion_scores: list,
    reason: str,
    overridden_by: str,
) -> CallScore:
    """A person corrects the AI's QA score. Validated against the rubric the call was scored with (rubric_snapshot);
    the AI's original numbers are kept in override_scores["ai_original"] (a second correction keeps the first original);
    total / percentage are recomputed and copied to calls.ai_score, so every dashboard and scorecard shows the corrected
    score. A later re-analysis leaves an overridden score alone (store_score). LookupError: no such score in the
    workspace; OverrideError: invalid input."""
    from datetime import datetime, timezone

    from app.models.call import Call

    score = db.query(CallScore).filter_by(id=score_id, tenant_id=tenant_id).first()
    if not score:
        raise LookupError("Score not found")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise OverrideError("Say why you are changing the score.")
    criteria = score.rubric_snapshot if isinstance(score.rubric_snapshot, list) else []
    methods = {c.get("id"): c.get("method", "YES_NO") for c in criteria if isinstance(c, dict)}
    human: dict[str, float] = {}
    for item in criterion_scores or []:
        cid = item.get("id") if isinstance(item, dict) else None
        if not cid or (methods and cid not in methods):
            raise OverrideError(f"Unknown criterion: {cid}")
        try:
            val = float(item.get("score"))
        except (TypeError, ValueError):
            raise OverrideError(f"Score for {cid} must be a number") from None
        hi = 3 if methods.get(cid) == "ZERO_THREE" else 1
        if not 0 <= val <= hi or (hi == 1 and val not in (0, 1)):
            raise OverrideError(f"Score for {cid} must be {'0 to 3' if hi == 3 else '0 or 1'}")
        human[cid] = val
    if not human:
        raise OverrideError("Change at least one criterion.")

    previous = score.override_scores if isinstance(score.override_scores, dict) else {}
    original = previous.get("ai_original") or {
        "criterion_scores": score.criterion_scores, "total_score": float(score.total_score or 0),
        "max_score": float(score.max_score or 0), "percentage": float(score.percentage or 0),
        "has_auto_fail": bool(score.has_auto_fail),
    }
    merged = []
    for c in original["criterion_scores"] or []:
        cid = c.get("id") if isinstance(c, dict) else None
        merged.append({**c, "score": human[cid], "overridden": True} if cid in human else c)
    for cid, val in human.items():          # a criterion the AI left out
        if cid not in {m.get("id") for m in merged if isinstance(m, dict)}:
            merged.append({"id": cid, "score": val, "overridden": True})
    total, max_possible, percentage = compute_score(criteria, merged)

    score.criterion_scores = merged
    score.total_score, score.max_score, score.percentage = total, max_possible, percentage
    if any(m == "AUTO_FAIL" for m in methods.values()):
        score.has_auto_fail = any(methods.get(m.get("id")) == "AUTO_FAIL" and float(m.get("score", 0)) == 0
                                  for m in merged if isinstance(m, dict))
    score.is_overridden = True
    score.override_scores = {"ai_original": original, "human": human}
    score.override_reason = reason[:1000]
    score.overridden_by = overridden_by
    score.overridden_at = datetime.now(timezone.utc).isoformat()
    call = db.query(Call).filter_by(id=score.call_id, tenant_id=tenant_id).first()
    if call is not None:
        call.ai_score = float(percentage)
    log.info("score_overridden", score_id=score_id, overridden_by=overridden_by, percentage=float(percentage))
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
