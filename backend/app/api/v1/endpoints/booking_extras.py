"""Booking page extras: payment schedule, security deposit, service requests, change guest.

  PUT    /bookings/{id}/schedule                 replace the payment plan
  PUT    /bookings/{id}/deposit                  set / update the security deposit
  DELETE /bookings/{id}/deposit
  POST   /bookings/{id}/service-requests         new request (also appears on My Day)
  PATCH  /bookings/{id}/service-requests/{rid}   edit, assign, mark done / reopen
  DELETE /bookings/{id}/service-requests/{rid}
  PATCH  /bookings/{id}/guest                    reassign the booking, or fix the guest's name / email
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.api.v1.endpoints.booking_detail import _detail, _get_stay
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.guest import Guest
from app.models.stay_finance import StayDeposit, StayInstalment, StayServiceRequest
from app.models.task import Task
from app.models.user import User, UserRole
from app.services import booking_service as bsvc
from app.services.identity_service import resolve_gid

router = APIRouter(prefix="/bookings", tags=["bookings"])

_EDIT = (UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS)
_MAX_INSTALMENTS = 12
_DEPOSIT_STATUSES = ("pending", "held", "released", "forfeited")


def _parse_date(raw: str, what: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{what} must be YYYY-MM-DD")


# ── Payment schedule ─────────────────────────────────────────────────────────

class InstalmentIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=100_000_000)
    due_date: str


class ScheduleIn(BaseModel):
    items: list[InstalmentIn] = Field(max_length=_MAX_INSTALMENTS)


@router.put("/{booking_id}/schedule")
def set_schedule(booking_id: str, body: ScheduleIn, current_user: User = Depends(require_roles(*_EDIT)),
                 db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    rows = [(i, _parse_date(i.due_date, "due_date")) for i in body.items]
    total = bsvc.financials_for(db, tid, [stay])[stay.id]["total"]
    if rows and sum(i.amount for i, _ in rows) > total + 0.005:
        raise HTTPException(status_code=422, detail=f"The instalments add up to more than the booking total (Rs {total:,.2f}).")
    db.query(StayInstalment).filter_by(tenant_id=tid, stay_id=stay.id).delete()
    for i, due in rows:
        db.add(StayInstalment(tenant_id=tid, stay_id=stay.id, label=i.label.strip(), amount=i.amount, due_date=due))
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action="booking.schedule_set",
                 target_type="booking", target_id=stay.id, payload={"instalments": len(rows)})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


# ── Security deposit ─────────────────────────────────────────────────────────

class DepositIn(BaseModel):
    amount: float = Field(gt=0, le=100_000_000)
    status: str = "pending"
    deducted: float = Field(0, ge=0)
    method: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)


@router.put("/{booking_id}/deposit")
def set_deposit(booking_id: str, body: DepositIn, current_user: User = Depends(require_roles(*_EDIT)),
                db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    if body.status not in _DEPOSIT_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(_DEPOSIT_STATUSES)}")
    if body.method is not None and body.method not in bsvc.PAYMENT_METHODS:
        raise HTTPException(status_code=422, detail=f"method must be one of {', '.join(bsvc.PAYMENT_METHODS)}")
    if body.deducted > body.amount + 0.005:
        raise HTTPException(status_code=422, detail="The deduction can't be more than the deposit.")
    if body.status != "released" and body.deducted:
        raise HTTPException(status_code=422, detail="A deduction only applies when the deposit is released.")

    dep = db.query(StayDeposit).filter_by(tenant_id=tid, stay_id=stay.id).first()
    before = dep.status if dep else None
    if dep is None:
        dep = StayDeposit(tenant_id=tid, stay_id=stay.id, amount=body.amount)
        db.add(dep)
    today = date.today()
    dep.amount, dep.status, dep.deducted = body.amount, body.status, body.deducted
    dep.method, dep.notes = body.method, body.notes
    if body.status in ("held", "released", "forfeited") and not dep.collected_on:
        dep.collected_on = today
    if body.status in ("released", "forfeited"):
        dep.resolved_on = dep.resolved_on or today
    else:
        dep.resolved_on = None
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action="booking.deposit_updated",
                 target_type="booking", target_id=stay.id,
                 payload={"amount": body.amount, "from": before, "to": body.status, "deducted": body.deducted})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


@router.delete("/{booking_id}/deposit")
def remove_deposit(booking_id: str, current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
                   db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    dep = db.query(StayDeposit).filter_by(tenant_id=current_user.tenant_id, stay_id=stay.id).first()
    if dep:
        append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="booking.deposit_removed",
                     target_type="booking", target_id=stay.id, payload={"amount": float(dep.amount), "status": dep.status})
        db.delete(dep)
        db.commit()
    return _detail(db, current_user.tenant_id, _get_stay(db, current_user, booking_id))


# ── Service requests ─────────────────────────────────────────────────────────

class RequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=1000)
    assigned_to: Optional[str] = None
    due_date: Optional[str] = None


class RequestUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=1000)
    assigned_to: Optional[str] = None       # "" clears the assignee
    due_date: Optional[str] = None          # "" clears the date
    status: Optional[str] = Field(None, pattern="^(open|done)$")


def _check_assignee(db: Session, tenant_id: str, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    if not db.query(User.id).filter_by(id=user_id, tenant_id=tenant_id, is_active=True).first():
        raise HTTPException(status_code=422, detail="That team member was not found.")
    return user_id


def _due_dt(due: Optional[date]) -> Optional[datetime]:
    return datetime.combine(due, time(9, 0), tzinfo=timezone.utc) if due else None


@router.post("/{booking_id}/service-requests", status_code=201)
def add_request(booking_id: str, body: RequestIn, current_user: User = Depends(require_roles(*_EDIT)),
                db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    assignee = _check_assignee(db, tid, body.assigned_to)
    due = _parse_date(body.due_date, "due_date") if body.due_date else None
    req = StayServiceRequest(tenant_id=tid, stay_id=stay.id, title=body.title.strip(), notes=body.notes,
                             assigned_to=assignee, due_date=due, created_by=current_user.id)
    db.add(req)
    db.flush()
    pname = stay.property.name if stay.property else "booking"
    task = Task(tenant_id=tid, title=f"{req.title} ({pname}, check-in {stay.check_in:%d %b})"[:255],
                due_date=_due_dt(due or stay.check_in), priority="medium", guest_id=stay.guest_id,
                inquiry_id=stay.inquiry_id, assigned_to=assignee, created_by=current_user.id)
    db.add(task)
    db.flush()
    req.task_id = task.id
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action="booking.request_added",
                 target_type="booking", target_id=stay.id, payload={"title": req.title})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


@router.patch("/{booking_id}/service-requests/{request_id}")
def update_request(booking_id: str, request_id: str, body: RequestUpdate,
                   current_user: User = Depends(require_roles(*_EDIT)), db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    req = db.query(StayServiceRequest).filter_by(id=request_id, stay_id=stay.id, tenant_id=tid).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    task = db.query(Task).filter_by(id=req.task_id, tenant_id=tid).first() if req.task_id else None

    if body.title is not None:
        req.title = body.title.strip()
    if body.notes is not None:
        req.notes = body.notes or None
    if body.assigned_to is not None:
        req.assigned_to = _check_assignee(db, tid, body.assigned_to or None)
        if task:
            task.assigned_to = req.assigned_to
    if body.due_date is not None:
        req.due_date = _parse_date(body.due_date, "due_date") if body.due_date else None
        if task:
            task.due_date = _due_dt(req.due_date or stay.check_in)
    if body.status is not None and body.status != req.status:
        req.status = body.status
        req.completed_at = datetime.now(timezone.utc) if body.status == "done" else None
        if task:
            task.is_done, task.completed_at = body.status == "done", req.completed_at
        append_audit(db, tenant_id=tid, actor_user_id=current_user.id,
                     action="booking.request_done" if body.status == "done" else "booking.request_reopened",
                     target_type="booking", target_id=stay.id, payload={"title": req.title})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


@router.delete("/{booking_id}/service-requests/{request_id}")
def remove_request(booking_id: str, request_id: str, current_user: User = Depends(require_roles(*_EDIT)),
                   db: Session = Depends(get_db)):
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    req = db.query(StayServiceRequest).filter_by(id=request_id, stay_id=stay.id, tenant_id=tid).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.task_id:
        db.query(Task).filter_by(id=req.task_id, tenant_id=tid).delete()
    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action="booking.request_removed",
                 target_type="booking", target_id=stay.id, payload={"title": req.title})
    db.delete(req)
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))


# ── Change guest ─────────────────────────────────────────────────────────────

class GuestChange(BaseModel):
    guest_id: Optional[str] = None      # move the booking to an existing guest
    phone: Optional[str] = Field(None, max_length=20)   # or find / create the guest by phone
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)


@router.patch("/{booking_id}/guest")
def change_guest(booking_id: str, body: GuestChange, current_user: User = Depends(require_roles(*_EDIT)),
                 db: Session = Depends(get_db)):
    """guest_id or phone: reassign the booking. Neither: correct the current guest's
    name / email. Phone numbers are never edited in place; identity (and its consent
    record) is resolved through identity_service, the only place that does it."""
    stay = _get_stay(db, current_user, booking_id)
    tid = current_user.tenant_id
    old_guest_id = stay.guest_id

    if body.guest_id or body.phone:
        if body.guest_id:
            target = db.query(Guest).filter_by(id=body.guest_id, tenant_id=tid, is_deleted=False).first()
            if not target:
                raise HTTPException(status_code=404, detail="Guest not found")
            target_id = target.id
        else:
            target_id, _created = resolve_gid(db=db, tenant_id=tid, signal_type="phone", value=body.phone.strip(),
                                              source="booking_change_guest",
                                              guest_fields={"name": (body.name or "").strip() or "Unknown"})
        stay.guest_id = target_id
        action = "booking.guest_changed"
    else:
        guest = db.query(Guest).filter_by(id=stay.guest_id, tenant_id=tid, is_deleted=False).first()
        if not guest:
            raise HTTPException(status_code=404, detail="Guest not found")
        if body.name is None and body.email is None:
            raise HTTPException(status_code=422, detail="Nothing to change.")
        if body.name is not None:
            if not body.name.strip():
                raise HTTPException(status_code=422, detail="Name can't be empty.")
            guest.name = body.name.strip()
        if body.email is not None:
            guest.email = body.email.strip() or None
        action = "booking.guest_edited"

    append_audit(db, tenant_id=tid, actor_user_id=current_user.id, action=action,
                 target_type="booking", target_id=stay.id,
                 payload={"from_guest": old_guest_id, "to_guest": stay.guest_id})
    db.commit()
    return _detail(db, tid, _get_stay(db, current_user, booking_id))
