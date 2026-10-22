"""What a PERSON says about an enquiry (CRM reporting, 22 Oct 2026; migration 169).

  set_lead_type    guest | b2b | partner (lead_types). Audited ``lead.type_changed`` with before/after.
  set_validation   "Valid enquiry?": valid yes/no with three checks (dates confirmed, budget fits, clear intent), an
                   optional note, who and when. ``valid=None`` clears it. Audited ``lead.validation_recorded`` with
                   before/after. This is the HUMAN review: the daily report keeps it apart from the automatic stage and
                   qualification numbers, and nothing automatic ever writes these columns.
  review_out       the card's view of both, for the lead list / detail (lead_list_extras).

Both writes check the lead page's visibility (a scoped role only on its own or unowned leads; 404 otherwise). The caller
commits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.user import User
from app.services import lead_types


class ReviewError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _lead(db: Session, user: User, inquiry_id: str, scope_user_id: Optional[str]) -> Inquiry:
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    if inq is None or (scope_user_id and inq.assigned_to and inq.assigned_to != scope_user_id):
        raise ReviewError(404, "Lead not found")
    return inq


def _validation(inq: Inquiry) -> dict:
    return {"status": inq.validation_status, "dates_confirmed": inq.validation_dates_confirmed,
            "budget_fits": inq.validation_budget_fits, "clear_intent": inq.validation_clear_intent,
            "note": inq.validation_note, "by_id": inq.validated_by,
            "at": inq.validated_at.isoformat() if inq.validated_at else None}


def review_out(inq: Inquiry, names: Optional[dict] = None) -> dict:
    v = _validation(inq)
    v["by_name"] = (names or {}).get(inq.validated_by) if inq.validated_by else None
    return {"lead_type": inq.lead_type or lead_types.GUEST, "validation": v}


def set_lead_type(db: Session, user: User, inquiry_id: str, lead_type: str, *, scope_user_id: Optional[str] = None) -> Inquiry:
    if lead_type not in lead_types.LEAD_TYPES:
        raise ReviewError(422, "Lead type must be guest, b2b or partner.")
    inq = _lead(db, user, inquiry_id, scope_user_id)
    before = inq.lead_type or lead_types.GUEST
    if before != lead_type:
        inq.lead_type = lead_type
        from app.core.audit import append_audit
        append_audit(db, tenant_id=user.tenant_id, action="lead.type_changed", actor_user_id=user.id, target_type="inquiry",
                     target_id=inq.id, payload={"before": before, "after": lead_type})
    return inq


def set_validation(db: Session, user: User, inquiry_id: str, *, valid: Optional[bool], dates_confirmed: Optional[bool] = None,
                   budget_fits: Optional[bool] = None, clear_intent: Optional[bool] = None, note: Optional[str] = None,
                   scope_user_id: Optional[str] = None) -> Inquiry:
    inq = _lead(db, user, inquiry_id, scope_user_id)
    before = _validation(inq)
    if valid is None:
        inq.validation_status = None
        inq.validation_dates_confirmed = inq.validation_budget_fits = inq.validation_clear_intent = None
        inq.validation_note = inq.validated_by = inq.validated_at = None
    else:
        inq.validation_status = "valid" if valid else "invalid"
        inq.validation_dates_confirmed, inq.validation_budget_fits, inq.validation_clear_intent = dates_confirmed, budget_fits, clear_intent
        inq.validation_note = (note or "").strip()[:300] or None
        inq.validated_by, inq.validated_at = user.id, datetime.now(timezone.utc)
    after = _validation(inq)
    from app.core.audit import append_audit
    append_audit(db, tenant_id=user.tenant_id, action="lead.validation_recorded", actor_user_id=user.id, target_type="inquiry",
                 target_id=inq.id, payload={"before": {k: v for k, v in before.items() if k != "at"},
                                            "after": {k: v for k, v in after.items() if k != "at"}})
    return inq
