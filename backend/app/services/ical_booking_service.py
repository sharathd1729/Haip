"""Turn a complete event of a shared Google Calendar into a real booking, and keep the two in step.

Rules (only for links that have vehicle keywords, i.e. a shared calendar):
  * An event becomes a booking when it gives a guest name, a phone number, a total and trip dates it can trust. Anything
    less stays a calendar block, as before.
  * The vehicle is NOT needed. An event that names no vehicle is booked on the "Unassigned" property and a task asks for a
    vehicle to be picked at check-in (the booking page's property field does that, with the usual clash check). Meanwhile it
    uses up one of the vehicles (vehicle_pool). An event naming two vehicles stays a block on both.
  * Google is the source for dates, total, advance and guest count while the booking is still "confirmed". Once someone
    checks the guest in, cancels, or picks the vehicle, the sync leaves those choices alone. Deleting the event cancels a
    confirmed booking.
  * The advance becomes a payment on the booking, updated in place if the event's advance changes.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.ical_feed import ICalEventBooking
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.task import Task
from app.services import booking_service as bsvc
from app.services import vehicle_pool
from app.services.identity_service import resolve_gid

log = structlog.get_logger()

SOURCE = "google_calendar"
ASSIGN_PREFIX = "Assign a vehicle:"
_CHILD = re.compile(r"(\d+)\s*(?:child|children|kid|kids|toddler|toddlers|infant|infants)", re.I)
_FIRST_INT = re.compile(r"\d+")


def head_count(text: Optional[str]) -> tuple[int, int]:
    """(adults, children) from lines like "5", "2 Adults + 1 Child", "7 pax + 1 toddler". Adults is at least 1."""
    text = text or ""
    children = sum(int(n) for n in _CHILD.findall(text))
    m = _FIRST_INT.search(text)
    adults = int(m.group(0)) if m else 1
    return max(1, min(adults, 60)), min(children, 30)


def candidate(details: dict, source: str, ev_start: str, ev_end: str, hits: list[str]) -> Optional[dict]:
    """What a booking would be made from, or None when the event is not complete enough to trust."""
    amounts = details.get("amounts") or {}
    name, phone, total = details.get("guest_name"), details.get("phone"), amounts.get("total")
    if not (name and phone and total) or len(hits) > 1:
        return None
    nights = (date.fromisoformat(ev_end) - date.fromisoformat(ev_start)).days
    if source != "description" and nights < 2:
        return None                      # a one-day event with no trip dates in the text: the real length is unknown
    adults, children = head_count(details.get("guests"))
    return {"name": name, "phone": phone, "total": float(total), "advance": float(amounts.get("advance") or 0),
            "adults": adults, "children": children}


def _assign_title(name: str, start: str, end: str) -> str:
    return f"{ASSIGN_PREFIX} {name} ({start} to {end})"[:255]


def _task(db: Session, tenant_id: str, title: str, stay: Stay, due: date) -> None:
    if db.query(Task.id).filter_by(tenant_id=tenant_id, title=title, is_done=False).first():
        return
    db.add(Task(tenant_id=tenant_id, title=title, priority="high", guest_id=stay.guest_id,
                due_date=datetime(due.year, due.month, due.day, tzinfo=timezone.utc)))


def _close_assign_tasks(db: Session, stay: Stay) -> None:
    now = datetime.now(timezone.utc)
    for t in db.query(Task).filter(Task.tenant_id == stay.tenant_id, Task.guest_id == stay.guest_id, Task.is_done.is_(False),
                                   Task.title.like(ASSIGN_PREFIX + "%")).all():
        t.is_done, t.completed_at = True, now


def _advance(db: Session, link: ICalEventBooking, stay: Stay, advance: float, today: date) -> None:
    pay = db.query(StayPayment).filter_by(id=link.payment_id, tenant_id=stay.tenant_id).first() if link.payment_id else None
    if pay is not None:
        if float(pay.amount) != advance and advance > 0:
            pay.amount = advance
        return
    if advance > 0 and not link.payment_id:
        pay = StayPayment(tenant_id=stay.tenant_id, stay_id=stay.id, kind="payment", amount=advance, method="other",
                          reference="Google Calendar", paid_on=today, notes="Advance written in the calendar event")
        db.add(pay)
        db.flush()
        link.payment_id = pay.id


def apply(db: Session, feed, key: str, ev: dict, details: dict, start: str, end: str, source: str,
          hits: list[str], today: date) -> Optional[str]:
    """Create or update the booking for one event. Returns "created", "updated", "unchanged", or None when the event
    is not bookable (the caller then keeps it as a block)."""
    cand = candidate(details, source, start, end, hits)
    link = db.query(ICalEventBooking).filter_by(feed_id=feed.id, event_key=key[:300], tenant_id=feed.tenant_id).first()
    check_in, check_out = date.fromisoformat(start), date.fromisoformat(end)

    if link is None:
        if cand is None:
            return None
        holder = vehicle_pool.placeholder_property(db, feed.tenant_id, feed.property_id)
        target, taken = holder.id, False
        if hits:
            if bsvc.find_conflicts(db, feed.tenant_id, hits[0], check_in, check_out):
                taken = True                                   # they asked for a vehicle that is not free: decide later
            else:
                target = hits[0]
        guest_id, _ = resolve_gid(db=db, tenant_id=feed.tenant_id, signal_type="phone", value=cand["phone"],
                                  source=SOURCE, guest_fields={"name": cand["name"]})
        stay = Stay(tenant_id=feed.tenant_id, guest_id=guest_id, property_id=target, check_in=check_in, check_out=check_out,
                    adults=cand["adults"], children=cand["children"], status="confirmed", total_amount=cand["total"],
                    currency="INR", special_requests=[], channel_source=SOURCE,
                    internal_notes=f"From Google Calendar: {(ev.get('summary') or '')[:200]}")
        db.add(stay)
        db.flush()
        link = ICalEventBooking(tenant_id=feed.tenant_id, feed_id=feed.id, event_key=key[:300], stay_id=stay.id)
        db.add(link)
        _advance(db, link, stay, cand["advance"], today)
        append_audit(db, tenant_id=feed.tenant_id, action="booking.created_from_calendar", target_type="booking", target_id=stay.id,
                     payload={"feed_id": feed.id, "property_id": target, "check_in": start, "check_out": end})
        if target == holder.id and check_out >= today:
            _task(db, feed.tenant_id, _assign_title(cand["name"], start, end), stay, check_in)
        if taken and check_out >= today:
            _task(db, feed.tenant_id, f"Vehicle taken: {cand['name']} asked for a vehicle that is not free ({start} to {end})"[:255], stay, check_in)
        return "created"

    stay = db.query(Stay).filter_by(id=link.stay_id, tenant_id=feed.tenant_id).first()
    if stay is None:                                           # erased or deleted on purpose: never bring it back
        return "unchanged"
    if stay.property_id not in vehicle_pool.placeholder_ids(db, feed.tenant_id):
        _close_assign_tasks(db, stay)
    if stay.status != "confirmed" or cand is None:
        return "unchanged"

    changed = False
    wanted = {"check_in": check_in, "check_out": check_out, "total_amount": cand["total"],
              "adults": cand["adults"], "children": cand["children"]}
    moved_dates = (stay.check_in, stay.check_out) != (check_in, check_out)
    for field, value in wanted.items():
        current = getattr(stay, field)
        if (float(current) if field == "total_amount" and current is not None else current) != value:
            setattr(stay, field, value)
            changed = True
    if hits and stay.property_id in vehicle_pool.placeholder_ids(db, feed.tenant_id) \
            and not bsvc.find_conflicts(db, feed.tenant_id, hits[0], check_in, check_out, exclude_stay_id=stay.id):
        stay.property_id, changed = hits[0], True              # the event now names a free vehicle
    if moved_dates and bsvc.find_conflicts(db, feed.tenant_id, stay.property_id, check_in, check_out, exclude_stay_id=stay.id):
        _task(db, feed.tenant_id, f"Dates changed in Google overlap another booking ({start} to {end})"[:255], stay, check_in)
    _advance(db, link, stay, cand["advance"], today)
    if changed:
        append_audit(db, tenant_id=feed.tenant_id, action="booking.updated_from_calendar", target_type="booking", target_id=stay.id,
                     payload={"feed_id": feed.id, "check_in": start, "check_out": end})
    return "updated" if changed else "unchanged"


def cancel_missing(db: Session, feed, present_keys: set[str], today: date) -> int:
    """Cancel confirmed, not-yet-finished bookings whose event is no longer in the calendar."""
    cancelled = 0
    for link in db.query(ICalEventBooking).filter_by(feed_id=feed.id, tenant_id=feed.tenant_id).all():
        if link.event_key in present_keys:
            continue
        stay = db.query(Stay).filter_by(id=link.stay_id, tenant_id=feed.tenant_id).first()
        if stay is not None and stay.status == "confirmed" and stay.check_out >= today:
            stay.status = "cancelled"
            _close_assign_tasks(db, stay)
            append_audit(db, tenant_id=feed.tenant_id, action="booking.cancelled_from_calendar", target_type="booking",
                         target_id=stay.id, payload={"feed_id": feed.id})
            cancelled += 1
            db.delete(link)                                    # if the event comes back it becomes a fresh booking
    return cancelled


def flag_over_capacity(db: Session, feed, property_ids: list[str], today: date) -> int:
    """Bookings without a vehicle outnumber the free vehicles on some day: raise one task for the first such day."""
    days = vehicle_pool.over_capacity_days(db, feed.tenant_id, property_ids, today, date.fromordinal(today.toordinal() + 365))
    if not days:
        return 0
    title = f"Not enough vehicles from {days[0]}: more bookings than free vehicles"[:255]
    if not db.query(Task.id).filter_by(tenant_id=feed.tenant_id, title=title, is_done=False).first():
        db.add(Task(tenant_id=feed.tenant_id, title=title, priority="high", due_date=datetime.now(timezone.utc)))
    return len(days)
