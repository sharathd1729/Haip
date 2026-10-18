"""Staff quotes on a lead: price a published package, add custom lines, issue it, hand the text to a person to send.

GET  /leads/{inquiry_id}/quotes/packages   published packages that fit the party/nights (what the picker shows)
POST /leads/{inquiry_id}/quotes/preview    price only, nothing stored (a refusal carries no price)
POST /leads/{inquiry_id}/quotes            issue: snapshot + audit (`quote.issued`) via quote_service.issue_quote
GET  /leads/{inquiry_id}/quotes            issued quotes, newest first, with whether the active one is still valid

Nothing here sends a message. The issue response carries the WhatsApp-ready text and the lead's official WhatsApp conversation (never
a personal-WhatsApp mirror) so a person opens the chat and sends it through the normal inbox path. Custom lines exist only on this
staff path (docs/HAIP_Priority_List.md §4 step 3); the AI's read path cannot add them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, or_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.user import User, UserRole
from app.services import package_pricing_service as pps
from app.services import quote_service, sales_gateway
from app.services.authz_service import require_capability

router = APIRouter(prefix="/leads", tags=["leads360"])

_read = Depends(require_capability("leads.read"))
_write = Depends(require_capability("leads.write"))
_module = Depends(require_module("ai_concierge"))


class CustomLine(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(gt=0, le=pps.MAX_CUSTOM_AMOUNT)
    reason: Optional[str] = Field(default=None, max_length=200)


class QuoteRequest(BaseModel):
    package_key: str = Field(min_length=1, max_length=60)
    check_in: date
    check_out: date
    adults: int = Field(ge=1, le=50)
    children: int = Field(default=0, ge=0, le=50)
    planned_km: Optional[Decimal] = Field(default=None, ge=0)
    extras: list[dict] = Field(default_factory=list, max_length=20)
    discount_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    vehicle_property_id: Optional[str] = None
    custom_lines: list[CustomLine] = Field(default_factory=list, max_length=pps.MAX_CUSTOM_LINES)


def _inquiry(db: Session, user: User, inquiry_id: str) -> Inquiry:
    """Same visibility as GET /leads/{id}: owner/manager see every lead, other roles their own and unclaimed ones."""
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    if inq is None or (user.role not in (UserRole.OWNER, UserRole.MANAGER) and inq.assigned_to and inq.assigned_to != user.id):
        raise HTTPException(status_code=404, detail="Lead not found")
    return inq


def _price(db: Session, user: User, body: QuoteRequest) -> pps.PackageQuote:
    return pps.quote(
        db, user.tenant_id, body.package_key, body.check_in, body.check_out, body.adults, body.children,
        planned_km=body.planned_km, extras=body.extras, discount_percent=body.discount_percent,
        vehicle_property_id=body.vehicle_property_id,
        custom_lines=[c.model_dump(mode="json") for c in body.custom_lines],
    )


def _official_conversation_id(db: Session, inq: Inquiry) -> Optional[str]:
    """The lead's open WhatsApp thread on the official number; personal-WhatsApp mirrors are read-only and never offered."""
    row = (db.query(Conversation.id)
           .filter(Conversation.tenant_id == inq.tenant_id, Conversation.channel == ChannelType.WHATSAPP, Conversation.is_open.is_(True),
                   Conversation.is_sample.is_(False), or_(Conversation.source.is_(None), Conversation.source != "personal_bridge"),
                   or_(Conversation.inquiry_id == inq.id, Conversation.guest_id == inq.guest_id))
           .order_by(case((Conversation.inquiry_id == inq.id, 0), else_=1), desc(Conversation.created_at))
           .first())
    return row[0] if row else None


def _out(row: InquiryQuote) -> dict:
    return {
        "id": row.id, "status": row.status, "is_active": row.is_active, "amount": str(row.amount), "currency": row.currency,
        "package_key": row.package_key, "check_in": row.check_in, "check_out": row.check_out, "guests": row.guests,
        "valid_until": row.valid_until, "created_at": row.created_at, "created_by": row.created_by, "snapshot": row.snapshot,
    }


@router.get("/{inquiry_id}/quotes/packages")
def quote_packages(inquiry_id: str, guests: Optional[int] = Query(default=None, ge=1, le=50), nights: Optional[int] = Query(default=None, ge=0, le=60),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_read, _m=_module):
    _inquiry(db, current_user, inquiry_id)
    return sales_gateway.list_packages(db, current_user.tenant_id, guests=guests, nights=nights, include_rates=True).to_dict()


@router.post("/{inquiry_id}/quotes/preview")
def preview_quote(inquiry_id: str, body: QuoteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  _cap=_write, _m=_module):
    _inquiry(db, current_user, inquiry_id)
    q = _price(db, current_user, body)
    if not q.ok:
        return {"ok": False, "reason": q.reason, "message": q.message}
    return {"ok": True, "quote": q.to_snapshot()}


@router.post("/{inquiry_id}/quotes", status_code=201)
def issue_quote(inquiry_id: str, body: QuoteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _cap=_write, _m=_module):
    inq = _inquiry(db, current_user, inquiry_id)
    q = _price(db, current_user, body)
    if not q.ok:
        raise HTTPException(status_code=422, detail={"code": q.reason, "message": q.message})
    try:
        row = quote_service.issue_quote(db, current_user.tenant_id, inq.id, q, actor_id=current_user.id)
    except quote_service.QuoteError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
    db.commit()
    guest = db.query(Guest).filter_by(id=inq.guest_id, tenant_id=current_user.tenant_id).first()
    return {"quote": _out(row), "message_text": quote_service.message_text(row, guest.name if guest else ""),
            "conversation_id": _official_conversation_id(db, inq)}


@router.get("/{inquiry_id}/quotes")
def list_quotes(inquiry_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_read, _m=_module):
    inq = _inquiry(db, current_user, inquiry_id)
    rows = (db.query(InquiryQuote).filter_by(tenant_id=current_user.tenant_id, inquiry_id=inq.id)
            .filter(InquiryQuote.snapshot.isnot(None)).order_by(desc(InquiryQuote.created_at)).limit(20).all())
    guest = db.query(Guest).filter_by(id=inq.guest_id, tenant_id=current_user.tenant_id).first()
    out = []
    for r in rows:
        item = _out(r)
        if r.is_active:
            item["validity"] = quote_service.check_still_valid(db, current_user.tenant_id, r)
            item["message_text"] = quote_service.message_text(r, guest.name if guest else "")
        out.append(item)
    return {"quotes": out, "conversation_id": _official_conversation_id(db, inq)}
