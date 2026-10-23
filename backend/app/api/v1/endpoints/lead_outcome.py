"""Why a lead was won / lost (lead_outcome). Scoped roles only on their own or unowned leads (404 otherwise).

GET  /leads/{inquiry_id}/outcome           the recorded reason (if any), the AI's proposal (status pending | ready |
                                           no_evidence | failed | stale) and the reason catalogue. leads.read.
POST /leads/{inquiry_id}/outcome/propose   {kind: won | lost} -- the Won/Lost dialog opened: queue the AI proposal (Celery
                                           lead_outcome.propose; never inline). A fresh one is reused. leads.write.
PUT  /leads/{inquiry_id}/outcome           {reason, note} -- confirm / change the reason of a lead ALREADY in a closed stage
                                           (e.g. Sold by a booking, reason proposed overnight). leads.write; audited
                                           lead.outcome_recorded. A move to Won / Lost itself goes through PATCH /inquiries.
"""
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.leads import _visibility_scope
from app.core.database import get_db
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.user import User
from app.services import lead_outcome
from app.services.authz_service import require_capability

log = structlog.get_logger()
router = APIRouter(prefix="/leads", tags=["leads360"])


class ProposeIn(BaseModel):
    kind: Literal["won", "lost"]


class OutcomeIn(BaseModel):
    reason: str = Field(max_length=30)
    note: Optional[str] = Field(default=None, max_length=300)


def _lead(db: Session, user: User, inquiry_id: str) -> Inquiry:
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    scope = _visibility_scope(user)
    if inq is None or (scope and inq.assigned_to and inq.assigned_to != scope):
        raise HTTPException(status_code=404, detail="Lead not found")
    return inq


def _out(db: Session, user: User, inq: Inquiry) -> dict:
    names = {}
    if inq.outcome_decided_by:
        names = dict(db.query(User.id, User.name).filter(User.tenant_id == user.tenant_id, User.id == inq.outcome_decided_by).all())
    return lead_outcome.view(inq, names)


@router.get("/{inquiry_id}/outcome")
def get_outcome(inquiry_id: str, current_user: User = Depends(require_capability("leads.read")), db: Session = Depends(get_db)) -> dict:
    return _out(db, current_user, _lead(db, current_user, inquiry_id))


@router.post("/{inquiry_id}/outcome/propose", status_code=202)
def propose_outcome(inquiry_id: str, body: ProposeIn, current_user: User = Depends(require_capability("leads.write")),
                    db: Session = Depends(get_db)) -> dict:
    inq = _lead(db, current_user, inquiry_id)
    queue = lead_outcome.request_proposal(db, inq, body.kind)
    db.commit()
    if queue:
        try:
            from app.workers.tasks.lead_outcome import propose
            propose.delay(inquiry_id=inq.id, tenant_id=current_user.tenant_id, kind=body.kind)
        except Exception as exc:  # noqa: BLE001 -- broker down: the dialog still works, a person picks the reason
            log.warning("lead_outcome_enqueue_failed", tenant_id=current_user.tenant_id, inquiry_id=inq.id, error=str(exc)[:200])
            inq.outcome_proposal = {**(inq.outcome_proposal or {}), "status": "failed"}
            db.commit()
    return _out(db, current_user, inq)


@router.put("/{inquiry_id}/outcome")
def put_outcome(inquiry_id: str, body: OutcomeIn, current_user: User = Depends(require_capability("leads.write")),
                db: Session = Depends(get_db)) -> dict:
    inq = _lead(db, current_user, inquiry_id)
    stage = db.query(PipelineStage).filter_by(id=inq.stage_id, tenant_id=current_user.tenant_id).first() if inq.stage_id else None
    kind = lead_outcome.kind_of(bool(stage and stage.is_closed_won), bool(stage and stage.is_closed_lost))
    if kind is None:
        raise HTTPException(status_code=409, detail={"code": "lead_not_closed", "message": "Move the lead to Won or Lost first."})
    from app.services.inquiry_service import OutcomeReasonRequired
    try:
        checked = lead_outcome.check(kind, {"reason": body.reason, "note": body.note}, by_person=True)
    except OutcomeReasonRequired as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    lead_outcome.record(db, inq, kind, checked, current_user.id)
    db.commit()
    return _out(db, current_user, inq)
