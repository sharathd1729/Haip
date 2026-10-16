"""Turn a complete event of a shared Google Calendar into a real booking, and keep the two in step.

Rules (only for links that have vehicle keywords, i.e. a shared calendar):
  * An event becomes a booking when it gives a guest name, a phone number, a total and trip dates it can trust. Anything
    less stays a calendar block, as before.
  * The vehicle is NOT needed. An event that names no vehicle (or one that is already taken) is booked on the FIRST FREE vehicle:
    Ratha 1, or Ratha 2 when Ratha 1 is busy on those dates. Only when every vehicle is taken does it sit on the "Unassigned"
    placeholder, with a task, so nothing is lost and the overbooking is visible. An event naming two vehicles stays a block on both.
  * If the guest already has a booking on those dates (someone entered it in the CRM first) the event is LINKED to it and
    locked, never booked a second time.
  * Google is the source for dates, total, advance and guest count while the booking is still "confirmed" and unlocked.
    Editing those fields in the CRM locks the booking (the CRM wins from then on) until someone unlocks it. Checking in,
    cancelling, or picking the vehicle are never undone. Deleting the event cancels a confirmed, unlocked booking.
  * A new booking is tied to the guest's lead when that is unambiguous, and the lead is moved to Sold (existing audited
    stage move). Two possible leads means no guess: a task asks which one.
  * The advance becomes a payment on the booking, updated in place if the event's advance changes.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.ical_feed import ICalEventBooking, ICalFeedVehicle
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.stay_finance import StayPayment
from app.models.task import Task
from app.services import booking_service as bsvc
from app.services import vehicle_pool
from app.services.identity_service import resolve_gid

log = structlog.get_logger()

SOURCE = "google_calendar"
ASSIGN_PREFIX = "Assign a vehicle:"
LEAD_PREFIX = "Which lead is this booking from?"
LOCK_FIELDS = ("check_in", "check_out", "total_amount", "adults", "children")
_LEAD_WINDOW = timedelta(days=180)          # a lead older than this is not assumed to be the source of a booking
_DATE_SLACK = timedelta(days=3)             # tie-break between several open leads: dates close to the booking
_CHILD = re.compile(r"(\d+)\s*(?:child|children|kid|kids|toddler|toddlers|infant|infants)", re.I)
_FIRST_INT = re.compile(r"\d+")


def head_count(text: Optional[str]) -> tuple[int, int]:
    """(adults, children) from lines like "5", "2 Adults + 1 Child", "7 pax + 1 toddler". Adults is at least 1."""
    text = text or ""
    children = sum(int(n) for n in _CHILD.findall(text))
    m = _FIRST_INT.search(text)
    adults = int(m.group(0)) if m else 1
    return max(1, min(adults, 60)), min(children, 30)


def missing_reasons(details: dict, source: str, ev_start: str, ev_end: str, hits: list[str]) -> list[str]:
    """Why an event is not a booking (empty = it is). Plain words, shown to the team."""
    out = []
    amounts = details.get("amounts") or {}
    if not details.get("guest_name"):
        out.append("no guest name")
    if not details.get("phone"):
        out.append("no phone number")
    if not amounts.get("total"):
        out.append("no total amount")
    if len(hits) > 1:
        out.append("names more than one vehicle")
    if source != "description" and (date.fromisoformat(ev_end) - date.fromisoformat(ev_start)).days < 2:
        out.append("no trip dates in the description")
    return out


def candidate(details: dict, source: str, ev_start: str, ev_end: str, hits: list[str]) -> Optional[dict]:
    """What a booking would be made from, or None when the event is not complete enough to trust."""
    if missing_reasons(details, source, ev_start, ev_end, hits):
        return None
    amounts = details.get("amounts") or {}
    adults, children = head_count(details.get("guests"))
    return {"name": details["guest_name"], "phone": details["phone"], "total": float(amounts["total"]),
            "advance": float(amounts.get("advance") or 0), "adults": adults, "children": children}


def _assign_title(name: str, start: str, end: str) -> str:
    return f"{ASSIGN_PREFIX} {name} ({start} to {end})"[:255]


def _task(db: Session, tenant_id: str, title: str, stay: Stay, due: date) -> None:
    if db.query(Task.id).filter_by(tenant_id=tenant_id, title=title, is_done=False).first():
        return
    db.add(Task(tenant_id=tenant_id, title=title, priority="high", guest_id=stay.guest_id,
                due_date=datetime(due.year, due.month, due.day, tzinfo=timezone.utc)))


def _close_tasks(db: Session, stay: Stay, prefix: str) -> None:
    now = datetime.now(timezone.utc)
    for t in db.query(Task).filter(Task.tenant_id == stay.tenant_id, Task.guest_id == stay.guest_id, Task.is_done.is_(False),
                                   Task.title.like(prefix + "%")).all():
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


# ─── Lead ─────────────────────────────────────────────────────────────────────

def _stages(db: Session, tenant_id: str) -> dict[str, PipelineStage]:
    rows = db.query(PipelineStage).filter_by(tenant_id=tenant_id).order_by(PipelineStage.order).all()
    won = next((s for s in rows if s.is_closed_won), None)
    return {"won": won, "by_id": {s.id: s for s in rows}}


def find_lead(db: Session, stay: Stay, today: date) -> tuple[Optional[Inquiry], bool]:
    """(the lead this booking came from, ambiguous). Only the guest's own OPEN leads count (not Sold, not Lost), and only
    recent ones. One candidate = that lead. Several = the one whose dates sit within three days of the booking, if exactly one
    does; otherwise it is ambiguous and nobody guesses."""
    stages = _stages(db, stay.tenant_id)["by_id"]
    floor = datetime.now(timezone.utc) - _LEAD_WINDOW
    taken = {r[0] for r in db.query(Stay.inquiry_id).filter(Stay.tenant_id == stay.tenant_id, Stay.inquiry_id.isnot(None),
                                                          Stay.id != stay.id).all()}
    open_leads = []
    for q in db.query(Inquiry).filter(Inquiry.tenant_id == stay.tenant_id, Inquiry.guest_id == stay.guest_id).all():
        st = stages.get(q.stage_id)
        if st is None or st.is_closed_won or st.is_closed_lost or q.id in taken:
            continue
        created = q.created_at.replace(tzinfo=timezone.utc) if q.created_at and q.created_at.tzinfo is None else q.created_at
        if created and created < floor:
            continue
        open_leads.append(q)
    if len(open_leads) <= 1:
        return (open_leads[0] if open_leads else None), False

    def near(q: Inquiry) -> bool:
        try:
            return abs(date.fromisoformat(q.check_in) - stay.check_in) <= _DATE_SLACK
        except (TypeError, ValueError):
            return False
    close = [q for q in open_leads if near(q)]
    return (close[0], False) if len(close) == 1 else (None, True)


def link_lead(db: Session, stay: Stay, today: date, reason: str = "Booked through Google Calendar") -> Optional[str]:
    """Tie the booking to its lead and mark the lead Sold. Returns the lead id, or None. Never raises: the booking stands."""
    try:
        lead, ambiguous = find_lead(db, stay, today)
        if ambiguous:
            _task(db, stay.tenant_id, f"{LEAD_PREFIX} {(stay.guest.name if stay.guest else 'Guest')} ({stay.check_in} to {stay.check_out})"[:255],
                  stay, stay.check_in)
            return None
        if lead is None:
            return None
        stay.inquiry_id = lead.id                      # set first: the won-lead path then sees a booking and makes none
        lead.check_in = lead.check_in or stay.check_in.isoformat()
        lead.check_out = lead.check_out or stay.check_out.isoformat()
        won = _stages(db, stay.tenant_id)["won"]
        if won is not None:
            from app.services import inquiry_service
            inquiry_service.update_stage_by_id(db, tenant_id=stay.tenant_id, inquiry_id=lead.id, new_stage_id=won.id,
                                               actor_user_id=None, actor_role="system", reason=reason)
        return lead.id
    except Exception as exc:  # noqa: BLE001
        log.warning("ical_booking_lead_link_failed", stay_id=stay.id, error=str(exc)[:200])
        return None


# ─── Create / update / cancel ─────────────────────────────────────────────────

def _existing_booking(db: Session, tenant_id: str, guest_id: str, start: date, end: date) -> Optional[Stay]:
    """A live booking for this guest on these dates that no calendar event owns yet (entered in the CRM first)."""
    owned = {r[0] for r in db.query(ICalEventBooking.stay_id).filter_by(tenant_id=tenant_id).all()}
    for s in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.guest_id == guest_id, Stay.status.in_(bsvc.ACTIVE_STATUSES),
                                   Stay.check_in < end, Stay.check_out > start).all():
        if s.id not in owned:
            return s
    return None


def _choose_vehicle(db: Session, feed, hits: list[str], check_in: date, check_out: date, exclude_stay_id: Optional[str] = None):
    """(property id or None, the event's own vehicle was taken, the Property chosen instead). The vehicle the event names when it
    is free, else the first free vehicle of the shared calendar; None when every vehicle is taken."""
    if hits and not bsvc.find_conflicts(db, feed.tenant_id, hits[0], check_in, check_out, exclude_stay_id=exclude_stay_id):
        return hits[0], False, None
    ids = [r[0] for r in db.query(ICalFeedVehicle.property_id).filter_by(feed_id=feed.id, tenant_id=feed.tenant_id).all()]
    free = bsvc.pick_free_property(db, feed.tenant_id, check_in, check_out, candidate_ids=ids, exclude_stay_id=exclude_stay_id) if ids else None
    return (free.id if free else None), bool(hits), free


def apply(db: Session, feed, key: str, ev: dict, details: dict, start: str, end: str, source: str,
          hits: list[str], today: date) -> Optional[str]:
    """Create or update the booking for one event. Returns "created", "linked", "updated", "unchanged", or None when the
    event is not bookable (the caller then keeps it as a block)."""
    cand = candidate(details, source, start, end, hits)
    link = db.query(ICalEventBooking).filter_by(feed_id=feed.id, event_key=key[:300], tenant_id=feed.tenant_id).first()
    check_in, check_out = date.fromisoformat(start), date.fromisoformat(end)

    if link is None:
        if cand is None:
            return None
        guest_id, _ = resolve_gid(db=db, tenant_id=feed.tenant_id, signal_type="phone", value=cand["phone"],
                                  source=SOURCE, guest_fields={"name": cand["name"]})
        mine = _existing_booking(db, feed.tenant_id, guest_id, check_in, check_out)
        if mine is not None:                                   # already in the CRM: tie the event to it, change nothing
            db.add(ICalEventBooking(tenant_id=feed.tenant_id, feed_id=feed.id, event_key=key[:300], stay_id=mine.id, locked=True))
            append_audit(db, tenant_id=feed.tenant_id, action="booking.linked_to_calendar", target_type="booking", target_id=mine.id,
                         payload={"feed_id": feed.id})
            return "linked"
        target, taken, free = _choose_vehicle(db, feed, hits, check_in, check_out)
        holder = None
        if target is None:                                     # every vehicle is taken: park it on the placeholder and say so
            holder = vehicle_pool.placeholder_property(db, feed.tenant_id, feed.property_id)
            target = holder.id
        stay = Stay(tenant_id=feed.tenant_id, guest_id=guest_id, property_id=target, check_in=check_in, check_out=check_out,
                    adults=cand["adults"], children=cand["children"], status="confirmed", total_amount=cand["total"],
                    currency="INR", special_requests=[], channel_source=SOURCE,
                    internal_notes=f"From Google Calendar: {(ev.get('summary') or '')[:200]}")
        db.add(stay)
        db.flush()
        link = ICalEventBooking(tenant_id=feed.tenant_id, feed_id=feed.id, event_key=key[:300], stay_id=stay.id)
        db.add(link)
        _advance(db, link, stay, cand["advance"], today)
        lead_id = link_lead(db, stay, today)
        append_audit(db, tenant_id=feed.tenant_id, action="booking.created_from_calendar", target_type="booking", target_id=stay.id,
                     payload={"feed_id": feed.id, "property_id": target, "check_in": start, "check_out": end, "inquiry_id": lead_id})
        if holder is not None and check_out >= today:
            _task(db, feed.tenant_id, _assign_title(cand["name"], start, end), stay, check_in)
        elif taken and free is not None and check_out >= today:
            _task(db, feed.tenant_id, f"Vehicle changed: {cand['name']} asked for a vehicle that is not free, booked on {free.name} ({start} to {end})"[:255], stay, check_in)
        return "created"

    stay = db.query(Stay).filter_by(id=link.stay_id, tenant_id=feed.tenant_id).first()
    if stay is None:                                           # erased or deleted on purpose: never bring it back
        return "unchanged"
    if stay.property_id not in vehicle_pool.placeholder_ids(db, feed.tenant_id):
        _close_tasks(db, stay, ASSIGN_PREFIX)
    if stay.status != "confirmed" or cand is None or link.locked:
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
    if stay.property_id in vehicle_pool.placeholder_ids(db, feed.tenant_id):
        target, _taken, _free = _choose_vehicle(db, feed, hits, check_in, check_out, exclude_stay_id=stay.id)
        if target is not None:                                 # a vehicle is free now (or the event names one): take it
            stay.property_id, changed = target, True
    if moved_dates and bsvc.find_conflicts(db, feed.tenant_id, stay.property_id, check_in, check_out, exclude_stay_id=stay.id):
        _task(db, feed.tenant_id, f"Dates changed in Google overlap another booking ({start} to {end})"[:255], stay, check_in)
    _advance(db, link, stay, cand["advance"], today)
    if changed:
        append_audit(db, tenant_id=feed.tenant_id, action="booking.updated_from_calendar", target_type="booking", target_id=stay.id,
                     payload={"feed_id": feed.id, "check_in": start, "check_out": end})
    return "updated" if changed else "unchanged"


def cancel_missing(db: Session, feed, present_keys: set[str], today: date) -> int:
    """Cancel confirmed, not-yet-finished, unlocked bookings whose event is no longer in the calendar. A locked one is the
    CRM's now, so it is left alone and a task says the event is gone."""
    cancelled = 0
    for link in db.query(ICalEventBooking).filter_by(feed_id=feed.id, tenant_id=feed.tenant_id).all():
        if link.event_key in present_keys:
            continue
        stay = db.query(Stay).filter_by(id=link.stay_id, tenant_id=feed.tenant_id).first()
        if stay is None or stay.status != "confirmed" or stay.check_out < today:
            continue
        if link.locked:
            _task(db, feed.tenant_id, f"Calendar event was deleted but this booking is locked: check it ({stay.check_in} to {stay.check_out})"[:255],
                  stay, stay.check_in)
            continue
        stay.status = "cancelled"
        _close_tasks(db, stay, ASSIGN_PREFIX)
        append_audit(db, tenant_id=feed.tenant_id, action="booking.cancelled_from_calendar", target_type="booking",
                     target_id=stay.id, payload={"feed_id": feed.id})
        cancelled += 1
        db.delete(link)                                        # if the event comes back it becomes a fresh booking
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


# ─── The lock (used by the booking endpoints) ────────────────────────────────

def calendar_link(db: Session, tenant_id: str, stay_id: str) -> Optional[ICalEventBooking]:
    return db.query(ICalEventBooking).filter_by(tenant_id=tenant_id, stay_id=stay_id).first()


def lock_for_manual_edit(db: Session, tenant_id: str, stay_id: str, changed_fields) -> bool:
    """Someone edited a calendar-owned field in the CRM: from now on the CRM's value stands. True when it locked."""
    if not set(changed_fields) & set(LOCK_FIELDS):
        return False
    link = calendar_link(db, tenant_id, stay_id)
    if link is None or link.locked:
        return False
    link.locked = True
    return True


def set_locked(db: Session, tenant_id: str, stay_id: str, locked: bool) -> Optional[ICalEventBooking]:
    link = calendar_link(db, tenant_id, stay_id)
    if link is not None:
        link.locked = locked
    return link


def sync_info(db: Session, tenant_id: str, stay_id: str) -> Optional[dict]:
    link = calendar_link(db, tenant_id, stay_id)
    return None if link is None else {"linked": True, "locked": bool(link.locked)}


# ─── What the calendar has done (settings page) ──────────────────────────────

def activity(db: Session, feed, today: date, limit: int = 40) -> dict:
    """Bookings this calendar made, and the upcoming events that did NOT become bookings, with why. No money, no phone."""
    from app.models.ical_feed import ICalEventDetail, ICalFeedVehicle
    from app.models.property import BlockedDate, Property
    from app.services import ical_event_details

    names = {p.id: p.name for p in db.query(Property).filter_by(tenant_id=feed.tenant_id).all()}
    holders = set(vehicle_pool.placeholder_ids(db, feed.tenant_id))
    bookings = []
    rows = (db.query(ICalEventBooking, Stay).join(Stay, Stay.id == ICalEventBooking.stay_id)
            .filter(ICalEventBooking.feed_id == feed.id, ICalEventBooking.tenant_id == feed.tenant_id)
            .order_by(Stay.check_in.desc()).limit(limit).all())
    for link, stay in rows:
        bookings.append({"stay_id": stay.id, "guest_name": stay.guest.name if stay.guest else None, "status": stay.status,
                         "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat(),
                         "vehicle": None if stay.property_id in holders else names.get(stay.property_id),
                         "locked": bool(link.locked), "lead_linked": bool(stay.inquiry_id)})
    rules = {r.property_id: [k for k in (r.keywords or []) if isinstance(k, str)]
             for r in db.query(ICalFeedVehicle).filter_by(feed_id=feed.id, tenant_id=feed.tenant_id).all()}
    skipped, seen = [], set()
    q = (db.query(ICalEventDetail, BlockedDate).join(BlockedDate, BlockedDate.id == ICalEventDetail.blocked_date_id)
         .filter(ICalEventDetail.feed_id == feed.id, ICalEventDetail.tenant_id == feed.tenant_id,
                 BlockedDate.is_active.is_(True), BlockedDate.blocked_to >= today.isoformat())
         .order_by(BlockedDate.blocked_from))
    for detail, block in q.all():
        if detail.event_uid in seen:
            continue
        seen.add(detail.event_uid)
        d = detail.details or {}
        hits = ical_event_details.match_vehicles((detail.title or "") + "\n" + (d.get("notes") or ""), rules)
        reasons = missing_reasons(d, detail.dates_source, block.blocked_from, block.blocked_to, hits) or ["not booked yet"]
        skipped.append({"title": detail.title, "from": block.blocked_from, "to": block.blocked_to, "reasons": reasons})
        if len(skipped) >= limit:
            break
    return {"bookings": bookings, "skipped": skipped}
