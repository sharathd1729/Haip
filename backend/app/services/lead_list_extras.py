"""The Leads list's lead type, "came from" and human-review bits (CRM reporting, 22 Oct 2026), kept out of leads_service.py.

  apply_filters   ?lead_type=guest,b2b,... and ?came_from=paid|organic|unknown (lead_paid.filter_sql)
  decorate        per card: lead_type, came_from (lead_paid.classify, batched for the page) and the validation review with
                  the reviewer's name. A failure here never breaks the list (the caller logs it).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.user import User
from app.services import lead_paid, lead_review_service, lead_types


def parse_types(value: Optional[str]) -> list[str]:
    """'guest,b2b' -> ['guest', 'b2b']; unknown values raise ValueError (the endpoint answers 422)."""
    types = [t.strip() for t in (value or "").split(",") if t.strip()]
    bad = [t for t in types if t not in lead_types.LEAD_TYPES]
    if bad:
        raise ValueError(f"Unknown lead type: {', '.join(bad)}")
    return types


def check_came_from(value: Optional[str]) -> Optional[str]:
    if value and value not in lead_paid.VALUES:
        raise ValueError("came_from must be paid, organic or unknown")
    return value or None


def apply_filters(db: Session, q, tenant_id: str, lead_type: Optional[str] = None, came_from: Optional[str] = None,
                  model=Inquiry):
    types = parse_types(lead_type)
    if types:
        q = q.filter(model.lead_type.in_(types)) if lead_types.GUEST not in types else \
            q.filter((model.lead_type.in_(types)) | (model.lead_type.is_(None)))
    if check_came_from(came_from):
        q = q.filter(lead_paid.filter_sql(db, tenant_id, came_from))
    return q


def decorate(db: Session, tenant_id: str, cards: list, inquiries: list) -> None:
    by_id = {i.id: i for i in inquiries}
    came = lead_paid.classify(db, tenant_id, inquiries)
    reviewers = {i.validated_by for i in inquiries if i.validated_by}
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id, User.id.in_(list(reviewers))).all()) if reviewers else {}
    for card in cards:
        inq = by_id.get(card.inquiry_id)
        if inq is None:
            continue
        view = lead_review_service.review_out(inq, names)
        card.lead_type = view["lead_type"]
        card.validation = view["validation"] if inq.validation_status else None
        card.came_from = came.get(inq.id, lead_paid.UNKNOWN)
