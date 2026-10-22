"""The lead page's Type selector and "Valid enquiry?" card (CRM reporting, 22 Oct 2026; lead_review_service).

PUT /leads/{inquiry_id}/lead-type    guest | b2b | partner (leads.write; audited lead.type_changed)
PUT /leads/{inquiry_id}/validation   a person's review: valid yes/no + dates confirmed / budget fits / clear intent + note;
                                     valid null clears it (leads.write; audited lead.validation_recorded)
Both answer the card's view ({lead_type, validation}); 404 for another workspace's lead or, for a scoped role, a teammate's.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.endpoints.leads import _visibility_scope
from app.core.database import get_db
from app.models.user import User
from app.schemas.lead_review import LeadTypeIn, ValidationIn
from app.services import lead_review_service as svc
from app.services.authz_service import require_capability

router = APIRouter(prefix="/leads", tags=["leads360"])


def _out(db: Session, user: User, inq) -> dict:
    names = {user.id: user.name} if inq.validated_by == user.id else {}
    return svc.review_out(inq, names)


@router.put("/{inquiry_id}/lead-type")
def put_lead_type(inquiry_id: str, body: LeadTypeIn, current_user: User = Depends(require_capability("leads.write")),
                  db: Session = Depends(get_db)) -> dict:
    try:
        inq = svc.set_lead_type(db, current_user, inquiry_id, body.lead_type, scope_user_id=_visibility_scope(current_user))
    except svc.ReviewError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    db.commit()
    return _out(db, current_user, inq)


@router.put("/{inquiry_id}/validation")
def put_validation(inquiry_id: str, body: ValidationIn, current_user: User = Depends(require_capability("leads.write")),
                   db: Session = Depends(get_db)) -> dict:
    try:
        inq = svc.set_validation(db, current_user, inquiry_id, valid=body.valid, dates_confirmed=body.dates_confirmed,
                                 budget_fits=body.budget_fits, clear_intent=body.clear_intent, note=body.note,
                                 scope_user_id=_visibility_scope(current_user))
    except svc.ReviewError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    db.commit()
    return _out(db, current_user, inq)
