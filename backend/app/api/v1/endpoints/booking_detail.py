"""One booking, in full: detail, add-ons, payments, payment links, activity.

  GET    /bookings/{id}                      everything the booking page shows
  POST   /bookings/{id}/addons               add a catalog or custom line
  PATCH  /bookings/{id}/addons/{line_id}     change quantity / price / note
  DELETE /bookings/{id}/addons/{line_id}
  POST   /bookings/{id}/payments             record a payment or refund
  DELETE /bookings/{id}/payments/{pay_id}    remove a mistaken entry (audited)
  POST   /bookings/{id}/payment-links        Razorpay link for the guest to pay
  POST   /bookings/{id}/dpdp-delete          start DPDP erasure for the guest
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.adapters.payments import razorpay as rzp
from app.api.v1.deps import get_current_user, require_roles
from app.services.authz_service import require_capability
from app.core.audit import append_audit
from app.core.database import get_db
from app.core.encryption import decrypt_credentials
from app.models.audit_event import AuditEvent
from app.models.base import gen_uuid
from app.models.integration import Integration
from app.models.property import PropertyAddOn, Stay
from app.models.stay_finance import StayAddOn, StayDeposit, StayPayment, StayPaymentLink, StayServiceRequest
from app.models.user import User, UserRole
from app.services import booking_service as bsvc
from app.services import ical_booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])

_EDIT = (UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS)
_ACTIVITY_LIMIT = 50


def _get_stay(db: Session, user: User, booking_id: str) -> Stay:
    stay = (
        db.query(Stay).options(joinedload(Stay.guest), joinedload(Stay.property))
        .filter(Stay.id == booking_id, Stay.tenant_id == user.tenant_id).first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Booking not found")
    return stay


def _addon_out(a: StayAddOn) -> dict:
    return {"id": a.id, "addon_id": a.addon_id, "name": a.name, "quantity": a.quantity,
            "unit_price": float(a.unit_price), "line_total": round(a.quantity * float(a.unit_price), 2), "notes": a.notes}


def _payment_out(p: StayPayment) -> dict:
    return {"id": p.id, "kind": p.kind, "amount": float(p.amount), "method": p.method, "reference": p.reference,
            "paid_on": p.paid_on.isoformat(), "notes": p.notes, "via_gateway": bool(p.external_id)}


def _link_out(link: StayPaymentLink) -> dict:
    return {"id": link.id, "short_url": link.short_url, "amount": float(link.amount), "status": link.status,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "created_at": link.created_at.isoformat() if link.created_at else None}


def _deposit_out(d: Optional[StayDeposit]) -> Optional[dict]:
    if not d:
        return None
    return {"id": d.id, "amount": float(d.amount), "status": d.status, "deducted": float(d.deducted or 0),
            "refundable": round(float(d.amount) - float(d.deducted or 0), 2) if d.status == "released" else 0.0,
            "method": d.method, "collected_on": d.collected_on.isoformat() if d.collected_on else None,
            "resolved_on": d.resolved_on.isoformat() if d.resolved_on else None, "notes": d.notes}


def _request_out(r: StayServiceRequest, names: dict) -> dict:
    return {"id": r.id, "title": r.title, "notes": r.notes, "status": r.status, "assigned_to": r.assigned_to,
            "assignee_name": names.get(r.assigned_to), "due_date": r.due_date.isoformat() if r.due_date else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None}


def _detail(db: Session, tenant_id: str, stay: Stay) -> dict:
    guest, prop = stay.guest, stay.property
    addons = db.query(StayAddOn).filter_by(tenant_id=tenant_id, stay_id=stay.id).order_by(StayAddOn.created_at).all()
    payments = db.query(StayPayment).filter_by(tenant_id=tenant_id, stay_id=stay.id).order_by(StayPayment.paid_on, StayPayment.created_at).all()
    links = db.query(StayPaymentLink).filter_by(tenant_id=tenant_id, stay_id=stay.id).order_by(StayPaymentLink.created_at.desc()).limit(10).all()
    fin = bsvc.financials_for(db, tenant_id, [stay])[stay.id]
    events = (
        db.query(AuditEvent).filter_by(tenant_id=tenant_id, target_type="booking", target_id=stay.id)
        .order_by(AuditEvent.created_at.desc()).limit(_ACTIVITY_LIMIT).all()
    )
    actor_ids = {e.actor_user_id for e in events if e.actor_user_id}
    names = {u.id: u.name for u in db.query(User).filter(User.id.in_(actor_ids)).all()} if actor_ids else {}
    requests = stay.special_requests if isinstance(stay.special_requests, list) else []
    schedule = bsvc.schedules_for(db, tenant_id, {stay.id: fin}).get(stay.id, [])
    deposit = db.query(StayDeposit).filter_by(tenant_id=tenant_id, stay_id=stay.id).first()
    reqs = db.query(StayServiceRequest).filter_by(tenant_id=tenant_id, stay_id=stay.id).order_by(StayServiceRequest.created_at).all()
    team = db.query(User).filter_by(tenant_id=tenant_id, is_active=True).order_by(User.name).all()
    team_names = {u.id: u.name for u in team}
    return {
        "id": stay.id, "status": stay.status, "channel": stay.channel_source,
        "pms_managed": bool(stay.hostaway_booking_id),
        "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat(),
        "nights": max(0, (stay.check_out - stay.check_in).days),
        "check_in_time": stay.check_in_time, "check_out_time": stay.check_out_time,
        "adults": stay.adults or 0, "children": stay.children or 0,
        "occasion": stay.occasion, "special_requests": requests[0] if requests else "",
        "internal_notes": stay.internal_notes or "", "concierge_notes": stay.concierge_notes or "",
        "inquiry_id": stay.inquiry_id,
        "calendar_sync": ical_booking_service.sync_info(db, tenant_id, stay.id),
        "schedule": schedule, "next_due": bsvc.next_due(schedule),
        "deposit": _deposit_out(deposit),
        "service_requests": [_request_out(r, team_names) for r in reqs],
        "assignees": [{"id": u.id, "name": u.name} for u in team],
        "created_at": stay.created_at.isoformat() if stay.created_at else None,
        "property": {"id": prop.id, "name": prop.name, "type": prop.type} if prop else None,
        "guest": {"id": guest.id, "name": guest.name, "phone": guest.phone, "email": guest.email} if guest else None,
        "financials": fin,
        "addons": [_addon_out(a) for a in addons],
        "payments": [_payment_out(p) for p in payments],
        "payment_links": [_link_out(link) for link in links],
        "available_addons": [
            {"id": c.id, "name": c.name, "description": c.description, "category": c.category,
             "price": float(c.price), "price_type": c.price_type,
             "suggested_quantity": bsvc.default_quantity(c.price_type, stay)}
            for c in (bsvc.catalog_for_property(db, tenant_id, stay.property_id) if prop else [])
        ],
        "activity": [
            {"id": e.id, "action": e.action, "at": e.created_at.isoformat() if e.created_at else None,
             "by": names.get(e.actor_user_id), "payload": e.payload or {}}
            for e in events
        ],
    }


@router.get("/{booking_id}")
def get_booking(booking_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _cap=Depends(require_capability("bookings.read"))):
    return _detail(db, current_user.tenant_id, _get_stay(db, current_user, booking_id))


class CalendarSyncBody(BaseModel):
    locked: bool


@router.put("/{booking_id}/calendar-sync")
def set_calendar_sync(booking_id: str, body: CalendarSyncBody, current_user: User = Depends(require_roles(*_EDIT)),
                      db: Session = Depends(get_db)):
    """Hand a booking made from a Google Calendar event back to the calendar (locked=false) or keep it as edited here."""
    stay = _get_stay(db, current_user, booking_id)
    link = ical_booking_service.set_locked(db, current_user.tenant_id, stay.id, body.locked)
    if link is None:
        raise HTTPException(status_code=404, detail="This booking did not come from a calendar event")
    append_audit(db, tenant_id=current_user.tenant_id, action="booking.calendar_sync_changed", actor_user_id=current_user.id,
                 target_type="booking", target_id=stay.id, payload={"locked": body.locked})
    db.commit()
    return {"calendar_sync": ical_booking_service.sync_info(db, current_user.tenant_id, stay.id)}


# ── Add-ons ──────────────────────────────────────────────────────────────────

class AddOnCreate(BaseModel):
    addon_id: Optional[str] = None           # catalog item; omit for a custom line
    name: Optional[str] = Field(None, max_length=255)
    quantity: Optional[int] = Field(None, ge=1, le=999)
    unit_price: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=1000)


class AddOnUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    quantity: Optional[int] = Field(None, ge=1, le=999)
    unit_price: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=1000)


@router.post("/{booking_id}/addons", status_code=201)
def add_addon(booking_id: str, body: AddOnCreate, current_user: User = Depends(require_roles(*_EDIT)),
              db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    if body.addon_id:
        cat = db.query(PropertyAddOn).filter_by(id=body.addon_id, tenant_id=tid, property_id=stay.property_id).first()
        if not cat:
            raise HTTPException(status_code=404, detail="That add-on is not on this property's list.")
        name = body.name or cat.name
        price = body.unit_price if body.unit_price is not None else float(cat.price)
        qty = body.quantity or bsvc.default_quantity(cat.price_type, stay)
    else:
        if not body.name or not body.name.strip():
            raise HTTPException(status_code=422, detail="Give the custom add-on a name.")
        if body.unit_price is None:
            raise HTTPException(status_code=422, detail="Give the custom add-on a price.")
        name, price, qty = body.name.strip(), body.unit_price, body.quantity or 1
    line = StayAddOn(tenant_id=tid, stay_id=stay.id, addon_id=body.addon_id, name=name, quantity=qty,
                     unit_price=price, notes=body.notes)
    db.add(line)
    db.flush()
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action="booking.addon_added",
                 target_type="booking", target_id=stay.id, payload={"name": name, "quantity": qty, "unit_price": price})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


@router.patch("/{booking_id}/addons/{line_id}")
def update_addon(booking_id: str, line_id: str, body: AddOnUpdate, current_user: User = Depends(require_roles(*_EDIT)),
                 db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    line = db.query(StayAddOn).filter_by(id=line_id, stay_id=stay.id, tenant_id=current_user.tenant_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Add-on line not found")
    if body.name is not None:
        line.name = body.name.strip()
    if body.quantity is not None:
        line.quantity = body.quantity
    if body.unit_price is not None:
        line.unit_price = body.unit_price
    if body.notes is not None:
        line.notes = body.notes or None
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="booking.addon_updated",
                 target_type="booking", target_id=stay.id,
                 payload={"name": line.name, "quantity": line.quantity, "unit_price": float(line.unit_price)})
    db.commit()
    return _detail(db, current_user.tenant_id, _get_stay(db, current_user, booking_id))


@router.delete("/{booking_id}/addons/{line_id}")
def remove_addon(booking_id: str, line_id: str, current_user: User = Depends(require_roles(*_EDIT)),
                 db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    line = db.query(StayAddOn).filter_by(id=line_id, stay_id=stay.id, tenant_id=current_user.tenant_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Add-on line not found")
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="booking.addon_removed",
                 target_type="booking", target_id=stay.id, payload={"name": line.name, "quantity": line.quantity})
    db.delete(line)
    db.commit()
    return _detail(db, current_user.tenant_id, _get_stay(db, current_user, booking_id))


# ── Payments ─────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    kind: str = Field("payment", pattern="^(payment|refund)$")
    amount: float = Field(gt=0, le=100_000_000)
    method: str = "upi"
    reference: Optional[str] = Field(None, max_length=120)
    paid_on: Optional[str] = None            # YYYY-MM-DD, default today
    notes: Optional[str] = Field(None, max_length=1000)


@router.post("/{booking_id}/payments", status_code=201)
def add_payment(booking_id: str, body: PaymentCreate, current_user: User = Depends(require_roles(*_EDIT)),
                db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    if body.method not in bsvc.PAYMENT_METHODS:
        raise HTTPException(status_code=422, detail=f"method must be one of {', '.join(bsvc.PAYMENT_METHODS)}")
    try:
        paid_on = date.fromisoformat(body.paid_on) if body.paid_on else date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="paid_on must be YYYY-MM-DD")
    if body.kind == "refund":
        received = bsvc.financials_for(db, tid, [stay])[stay.id]["paid"]
        if body.amount > received + 0.005:
            raise HTTPException(status_code=422, detail=f"Cannot refund more than has been received (Rs {received:,.2f}).")
    pay = StayPayment(tenant_id=tid, stay_id=stay.id, kind=body.kind, amount=body.amount, method=body.method,
                      reference=body.reference, paid_on=paid_on, notes=body.notes, created_by=current_user.id)
    db.add(pay)
    db.flush()
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action=f"booking.{body.kind}_recorded",
                 target_type="booking", target_id=stay.id,
                 payload={"amount": body.amount, "method": body.method, "reference": body.reference})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


@router.delete("/{booking_id}/payments/{payment_id}")
def delete_payment(booking_id: str, payment_id: str,
                   current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
                   db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    pay = db.query(StayPayment).filter_by(id=payment_id, stay_id=stay.id, tenant_id=current_user.tenant_id).first()
    if not pay:
        raise HTTPException(status_code=404, detail="Payment not found")
    if pay.external_id:
        raise HTTPException(status_code=409, detail="This payment came from Razorpay and can't be deleted here. Record a refund instead.")
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="booking.payment_deleted",
                 target_type="booking", target_id=stay.id,
                 payload={"kind": pay.kind, "amount": float(pay.amount), "method": pay.method, "reference": pay.reference})
    db.delete(pay)
    db.commit()
    return _detail(db, current_user.tenant_id, _get_stay(db, current_user, booking_id))


# ── Razorpay payment link ────────────────────────────────────────────────────

class PaymentLinkCreate(BaseModel):
    amount: Optional[float] = Field(None, gt=0, le=100_000_000)   # default: the outstanding balance
    expires_in_days: int = Field(3, ge=1, le=30)


def razorpay_credentials(db: Session, tenant_id: str) -> Optional[dict]:
    intg = db.query(Integration).filter_by(tenant_id=tenant_id, kind="razorpay", status="active").first()
    if not intg or not intg.credentials_kms_blob:
        return None
    blob = bytes(intg.credentials_kms_blob) if isinstance(intg.credentials_kms_blob, memoryview) else intg.credentials_kms_blob
    return decrypt_credentials(blob)


@router.post("/{booking_id}/payment-links", status_code=201)
def create_payment_link(booking_id: str, body: PaymentLinkCreate, current_user: User = Depends(require_roles(*_EDIT)),
                        db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    creds = razorpay_credentials(db, tid)
    if not creds:
        raise HTTPException(status_code=422, detail="Razorpay is not connected. Add your keys in Settings > Payments first.")
    outstanding = bsvc.financials_for(db, tid, [stay])[stay.id]["outstanding"]
    amount = body.amount if body.amount is not None else outstanding
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Nothing is outstanding on this booking.")
    if amount < 1:
        raise HTTPException(status_code=422, detail="Razorpay links need at least ₹1. Record smaller amounts as a manual payment.")
    guest, prop = stay.guest, stay.property
    # Razorpay rejects a reused reference_id, so each link carries its own id
    # (a booking often needs a second link: balance after advance, or after expiry).
    link_id = gen_uuid()
    expires = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
    phone = guest.phone if guest and guest.phone and not guest.phone.startswith("DELETED_") else None
    try:
        res = rzp.create_payment_link(
            creds["key_id"], creds["key_secret"], amount_inr=amount,
            description=f"{prop.name if prop else 'Stay'}, {stay.check_in:%d %b} to {stay.check_out:%d %b %Y}",
            reference_id=link_id.replace("-", ""),
            customer_name=guest.name if guest else None, customer_phone=phone,
            customer_email=guest.email if guest else None,
            expire_by=int(expires.timestamp()) if expires.timestamp() > time.time() + 900 else None,
            notes={"haip_stay_id": stay.id, "haip_tenant_id": tid},
        )
    except rzp.RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    link = StayPaymentLink(id=link_id, tenant_id=tid, stay_id=stay.id, provider="razorpay", external_id=res["id"],
                           short_url=res["short_url"], amount=amount, status="created", expires_at=expires,
                           created_by=current_user.id)
    db.add(link)
    db.flush()
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action="booking.payment_link_created",
                 target_type="booking", target_id=stay.id, payload={"amount": amount, "link_id": res["id"]})
    db.commit()
    return _link_out(link)


# ── DPDP ─────────────────────────────────────────────────────────────────────

@router.post("/{booking_id}/dpdp-delete")
def start_guest_erasure(booking_id: str,
                        current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
                        db: Session = Depends(get_db)):
    """Same effect as POST /guests/{id}/dpdp/delete: 30-day grace period, then purge."""
    stay = _get_stay(db, current_user, booking_id)
    if not stay.guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    guest = stay.guest
    if guest.deletion_state != "pending":
        now = datetime.now(timezone.utc).isoformat()
        guest.deletion_state, guest.deletion_requested_at, guest.is_deleted = "pending", now, True
        append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                     action="dpdp.delete_requested", target_type="guest", target_id=guest.id,
                     payload={"deletion_requested_at": now, "from_booking": stay.id})
        db.commit()
    return {"status": "pending", "guest_id": guest.id}
