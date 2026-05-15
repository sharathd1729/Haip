from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.score import Rubric, CallScore
from app.schemas.score import CallScoreOut, ScoreOverrideRequest
from app.services.qa_service import override_score
from app.core.audit import append_audit

router = APIRouter(prefix="/qa", tags=["qa"])


@router.get("/rubrics")
def list_rubrics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Rubric).filter_by(tenant_id=current_user.tenant_id, is_active=True).all()


@router.get("/scores/{score_id}", response_model=CallScoreOut)
def get_score(score_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    score = db.query(CallScore).filter_by(id=score_id, tenant_id=current_user.tenant_id).first()
    if not score:
        raise HTTPException(status_code=404, detail="Score not found")
    return score


@router.post("/scores/{score_id}/override", response_model=CallScoreOut)
def override_qa_score(
    score_id: str,
    body: ScoreOverrideRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    score = override_score(
        db, current_user.tenant_id, score_id,
        criterion_scores=body.criterion_scores,
        reason=body.reason,
        overridden_by=current_user.id,
    )
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                 action="score.override", target_type="call_score", target_id=score_id,
                 payload={"reason": body.reason})
    db.commit()
    db.refresh(score)
    return score
