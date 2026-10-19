"""Booking money and conflict rules, shared by the list and detail endpoints.

Amount owed  = stay charge (Stay.total_amount) + sum(add-on qty * unit price)
Amount paid  = sum(payments) - sum(refunds)
Outstanding  = owed - paid (never below zero; an overpayment shows as paid)
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.property import BlockedDate, Property, PropertyAddOn, Stay
from app.models.stay_finance import StayAddOn, StayInstalment, StayPayment
from app.services import vehicle_pool

ACTIVE_STATUSES = ("confirmed", "checked_in")
PAYMENT_METHODS = ("cash", "upi", "card", "bank_transfer", "other")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def payment_status(owed: float, paid: float) -> str:
    if paid <= 0:
        return "unpaid"
    if owed > 0 and paid + 0.005 >= owed:
        return "paid"
    return "partial"


def summarize(charge, addons_total, paid) -> dict:
    charge, addons_total, paid = _f(charge), _f(addons_total), _f(paid)
    owed = charge + addons_total
    return {
        "stay_charge": round(charge, 2),
        "addons_total": round(addons_total, 2),
        "total": round(owed, 2),
        "paid": round(paid, 2),
        "outstanding": round(max(owed - paid, 0.0), 2),
        "payment_status": payment_status(owed, paid),
    }


def financials_for(db: Session, tenant_id: str, stays: Iterable[Stay]) -> dict[str, dict]:
    """Money summary per stay id, in two grouped queries (no per-row lookups)."""
    stays = list(stays)
    ids = [s.id for s in stays]
    addons: dict[str, float] = {}
    paid: dict[str, float] = {}
    if ids:
        for sid, total in (
            db.query(StayAddOn.stay_id, func.sum(StayAddOn.quantity * StayAddOn.unit_price))
            .filter(StayAddOn.tenant_id == tenant_id, StayAddOn.stay_id.in_(ids))
            .group_by(StayAddOn.stay_id).all()
        ):
            addons[sid] = _f(total)
        signed = case((StayPayment.kind == "refund", -StayPayment.amount), else_=StayPayment.amount)
        for sid, total in (
            db.query(StayPayment.stay_id, func.sum(signed))
            .filter(StayPayment.tenant_id == tenant_id, StayPayment.stay_id.in_(ids))
            .group_by(StayPayment.stay_id).all()
        ):
            paid[sid] = _f(total)
    return {s.id: summarize(s.total_amount, addons.get(s.id), paid.get(s.id)) for s in stays}


def default_quantity(price_type: Optional[str], stay: Stay) -> int:
    """Sensible starting quantity for a catalog add-on; staff can change it."""
    if price_type == "per_night":
        return max(1, (stay.check_out - stay.check_in).days)
    if price_type == "per_person":
        return max(1, (stay.adults or 1) + (stay.children or 0))
    return 1


def catalog_for_property(db: Session, tenant_id: str, property_id: str) -> list[PropertyAddOn]:
    return (
        db.query(PropertyAddOn)
        .filter_by(tenant_id=tenant_id, property_id=property_id, is_active=True)
        .order_by(PropertyAddOn.sort_order, PropertyAddOn.name)
        .all()
    )


TIGHT_TURNAROUND = timedelta(hours=2)      # less than this between two trips on one vehicle = a warning, not a block
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _at(d: date, t: Optional[str]) -> Optional[datetime]:
    """date + "HH:MM" -> a naive local datetime, or None when the time is missing or malformed."""
    if not t or not _TIME.match(t):
        return None
    return datetime.combine(d, time(int(t[:2]), int(t[3:])))


def _timed(check_in: date, check_out: date, ci_time: Optional[str], co_time: Optional[str]) -> Optional[tuple[datetime, datetime]]:
    a, b = _at(check_in, ci_time), _at(check_out, co_time)
    return (a, b) if a is not None and b is not None and b > a else None


def _booking_row(s: Stay) -> dict:
    return {"type": "booking", "id": s.id, "from": s.check_in.isoformat(), "to": s.check_out.isoformat(),
            "from_time": s.check_in_time, "to_time": s.check_out_time,
            "guest": (s.guest.name if s.guest is not None else None)}


def find_conflicts(db: Session, tenant_id: str, property_id: str, check_in: date, check_out: date,
                   exclude_stay_id: Optional[str] = None, ignore_unassigned: bool = False,
                   check_in_time: Optional[str] = None, check_out_time: Optional[str] = None) -> list[dict]:
    """Other bookings and blocks that overlap [check_in, check_out) on this property. ``ignore_unassigned`` skips the "bookings
    with no vehicle yet already need the other vehicles" rule (used when those bookings are being given a vehicle one by one).

    Times (owner decision, Oct 2026): when this booking has a pickup and a return time ("HH:MM") AND the other booking has
    both too, they clash only if [pickup, return) overlaps; a same-day turnaround with a gap is fine (``turnarounds`` warns
    under 2 hours). Whenever either side has no times the date rule applies unchanged: [check_in, check_out) by date, a
    same-day stay occupying its day. Calendar blocks and the unassigned-bookings rule are always by date. Called without
    times (the iCal import, the paid-quote link, the sales agent) the result is exactly the date rule."""
    prop = db.query(Property.name).filter(Property.id == property_id, Property.tenant_id == tenant_id).first()
    if prop and vehicle_pool.is_placeholder_name(prop[0]):
        return []                                  # the "Unassigned" holder takes any number of bookings
    ci, co = check_in.isoformat(), check_out.isoformat()
    # a same-day stay still occupies its day
    end = co if check_out > check_in else (date.fromordinal(check_in.toordinal() + 1)).isoformat()
    span = _timed(check_in, check_out, check_in_time, check_out_time)
    out: list[dict] = []
    q = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id == property_id, Stay.status.in_(ACTIVE_STATUSES))
    if span is None:
        q = q.filter(Stay.check_in < end, Stay.check_out > ci)
    else:                                          # widen by a day each side, then decide per booking below
        q = q.filter(Stay.check_in <= check_out, Stay.check_out >= check_in)
    if exclude_stay_id:
        q = q.filter(Stay.id != exclude_stay_id)
    for s in q.all():
        other = _timed(s.check_in, s.check_out, s.check_in_time, s.check_out_time) if span is not None else None
        if other is not None:
            if not (span[0] < other[1] and other[0] < span[1]):
                continue
        elif span is not None and not (s.check_in.isoformat() < end and s.check_out.isoformat() > ci):
            continue
        out.append(_booking_row(s))
    for b in db.query(BlockedDate).filter(
        BlockedDate.tenant_id == tenant_id, BlockedDate.property_id == property_id,
        BlockedDate.is_active.is_(True), BlockedDate.blocked_from < end, BlockedDate.blocked_to > ci,
    ).all():
        out.append({"type": "block", "id": b.id, "from": b.blocked_from, "to": b.blocked_to, "reason": b.reason})
    # Vehicles sharing a calendar: bookings with no vehicle yet use up one of them (see vehicle_pool).
    if not out and not ignore_unassigned:
        short = vehicle_pool.shortage_days(db, tenant_id, property_id, check_in, check_out, exclude_stay_id)
        if short:
            out.append({"type": "unassigned_bookings", "from": short[0], "to": short[-1],
                        "message": "Bookings that have no vehicle yet already need the other vehicles on these days."})
    return out


def turnarounds(db: Session, tenant_id: str, property_id: str, check_in: date, check_out: date, check_in_time: Optional[str],
                check_out_time: Optional[str], exclude_stay_id: Optional[str] = None) -> list[dict]:
    """Bookings on this vehicle that do not clash but leave less than 2 hours between the two trips (a warning: the caravan
    needs cleaning). Only when both bookings have times; [] otherwise."""
    span = _timed(check_in, check_out, check_in_time, check_out_time)
    if span is None:
        return []
    q = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id == property_id, Stay.status.in_(ACTIVE_STATUSES),
                              Stay.check_in <= check_out + timedelta(days=1), Stay.check_out >= check_in - timedelta(days=1))
    if exclude_stay_id:
        q = q.filter(Stay.id != exclude_stay_id)
    out = []
    for s in q.all():
        other = _timed(s.check_in, s.check_out, s.check_in_time, s.check_out_time)
        if other is None or (span[0] < other[1] and other[0] < span[1]):
            continue
        gap = span[0] - other[1] if other[1] <= span[0] else other[0] - span[1]
        if gap < TIGHT_TURNAROUND:
            out.append({**_booking_row(s), "returns_before": other[1] <= span[0], "gap_minutes": int(gap.total_seconds() // 60)})
    return out


def _natural(name: str):
    """"Ratha 2" sorts before "Ratha 10"."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name or "")]


def pick_free_property(db: Session, tenant_id: str, check_in: date, check_out: date, candidate_ids: Optional[Iterable[str]] = None,
                       exclude_stay_id: Optional[str] = None, ignore_unassigned: bool = False,
                       check_in_time: Optional[str] = None, check_out_time: Optional[str] = None) -> Optional[Property]:
    """The first vehicle (by name: Ratha 1, then Ratha 2) with nothing booked or blocked on these dates, or None when all are taken.

    This is how a booking made without choosing a vehicle is assigned: the first booking lands on Ratha 1, an overlapping one
    falls through to Ratha 2. The "Unassigned" placeholder is never a candidate. With pickup/return times, a vehicle with a
    comfortable turnaround is preferred over one with a tight (< 2 h) turnaround; without times the result is the date rule's."""
    q = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    if candidate_ids is not None:
        q = q.filter(Property.id.in_(list(candidate_ids)))
    tight = None
    for prop in sorted((p for p in q.all() if not vehicle_pool.is_placeholder_name(p.name)), key=lambda p: _natural(p.name)):
        if find_conflicts(db, tenant_id, prop.id, check_in, check_out, exclude_stay_id, ignore_unassigned,
                          check_in_time=check_in_time, check_out_time=check_out_time):
            continue
        if not turnarounds(db, tenant_id, prop.id, check_in, check_out, check_in_time, check_out_time, exclude_stay_id):
            return prop
        tight = tight or prop
    return tight


# ── Creating a booking ───────────────────────────────────────────────────────

class BookingCreateError(Exception):
    """Why a booking could not be made, safe to show; ``status`` is the HTTP status POST /bookings answers with."""
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def create_booking(db: Session, tenant_id: str, *, guest_id: str, prop: Property, check_in: date, check_out: date,
                   adults: int = 1, children: int = 0, total_amount=None, inquiry_id: Optional[str] = None,
                   status: str = "confirmed", special_requests: Optional[str] = None, occasion: Optional[str] = None,
                   channel_source: str = "direct", check_in_time: Optional[str] = None, check_out_time: Optional[str] = None,
                   internal_notes: Optional[str] = None, actor_user_id: Optional[str] = None, actor_role: str = "system",
                   reason: str = "Booked in HAIP", strict_stage: bool = True, audit_extra: Optional[dict] = None,
                   gst_percent=None) -> Stay:
    """The one way HAIP code makes a booking (POST /bookings, a paid quote link). Ties it to its lead and marks that lead
    Sold through the audited stage move, then audits ``booking.created``. Flushes; the caller commits. Raises
    BookingCreateError when the lead is not this guest's (422) or already has a booking (409).

    ``strict_stage=False`` (a payment webhook): a lead that cannot move to Sold (e.g. it was marked Lost) is logged and
    audited instead of failing, because the guest has paid and the booking must stand. A lead still on the legacy stage enum
    only (no stage_id) first gets the stage_id its enum stage means (no move), so the same audited move and stage hooks run.
    ``gst_percent``: the GST slab the total was priced with (the new-booking flow); the invoice then uses it."""
    from app.core.audit import append_audit
    from app.models.base import gen_uuid
    from app.models.inquiry import Inquiry

    stay = Stay(id=gen_uuid(), tenant_id=tenant_id, guest_id=guest_id, property_id=prop.id, check_in=check_in, check_out=check_out,
                adults=adults, children=children, status=status, total_amount=total_amount, currency="INR",
                special_requests=[special_requests] if special_requests else [], occasion=occasion, channel_source=channel_source,
                check_in_time=check_in_time, check_out_time=check_out_time, internal_notes=internal_notes,
                gst_percent=gst_percent)
    if inquiry_id:
        lead = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
        if lead is None or lead.guest_id != guest_id:
            raise BookingCreateError("That lead does not belong to this guest", 422)
        if db.query(Stay.id).filter(Stay.tenant_id == tenant_id, Stay.inquiry_id == lead.id, Stay.status != "cancelled").first():
            raise BookingCreateError("That lead already has a booking", 409)
        stay.inquiry_id = lead.id
    db.add(stay)
    db.flush()
    # A booking keeps the source and agent of the lead it came from: tie it to the lead (and mark that lead Sold through the
    # audited stage move) so reports never show it as "Other" / "Unassigned" when the attribution exists. When the guest has no
    # single open lead, nothing is guessed and the booking stays unattributed.
    from app.services import ical_booking_service as _lead_link
    if stay.inquiry_id is None:
        _lead_link.link_lead(db, stay, date.today(), reason=reason)
    else:
        from app.models.pipeline_stage import PipelineStage
        from app.services import inquiry_service as _inq
        won = db.query(PipelineStage).filter_by(tenant_id=tenant_id, is_closed_won=True).order_by(PipelineStage.order).first()
        lead = db.query(Inquiry).filter_by(id=stay.inquiry_id, tenant_id=tenant_id).first()
        if won is not None and lead is not None and lead.stage_id is None:
            from app.models.inquiry import InquiryStage
            lead.stage_id = _inq._stage_id_for(db, tenant_id, lead.stage or InquiryStage.NEW)
        if won is not None and lead is not None and lead.stage_id != won.id:
            try:
                _inq.update_stage_by_id(db, tenant_id=tenant_id, inquiry_id=lead.id, new_stage_id=won.id,
                                        actor_user_id=actor_user_id, actor_role=actor_role, reason=reason)
            except (_inq.InvalidStageTransition, ValueError) as exc:
                if strict_stage:
                    raise
                append_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="booking.lead_not_moved",
                             target_type="inquiry", target_id=lead.id, payload={"booking_id": stay.id, "reason": str(exc)[:300]})
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="booking.created", target_type="booking", target_id=stay.id,
                 payload={"property_id": prop.id, "check_in": check_in.isoformat(), "check_out": check_out.isoformat(),
                          "inquiry_id": stay.inquiry_id, **(audit_extra or {})})
    return stay


# ── Payment schedule ─────────────────────────────────────────────────────────

def allocate_schedule(instalments: list, paid: float, today: Optional[date] = None) -> list[dict]:
    """Apply what has been received to the instalments in due-date order."""
    today = today or date.today()
    remaining = _f(paid)
    out = []
    for i in sorted(instalments, key=lambda x: (x.due_date, x.created_at or x.due_date)):
        amount = _f(i.amount)
        applied = max(0.0, min(remaining, amount))
        remaining -= applied
        if applied + 0.005 >= amount:
            status = "paid"
        elif i.due_date < today:
            status = "overdue"
        else:
            status = "partial" if applied > 0 else "due"
        out.append({"id": i.id, "label": i.label, "amount": round(amount, 2), "due_date": i.due_date.isoformat(),
                    "paid": round(applied, 2), "status": status})
    return out


def next_due(schedule: list[dict]) -> Optional[dict]:
    for row in schedule:
        if row["status"] != "paid":
            return {"amount": round(row["amount"] - row["paid"], 2), "due_date": row["due_date"],
                    "overdue": row["status"] == "overdue", "label": row["label"]}
    return None


def schedules_for(db: Session, tenant_id: str, fins: dict[str, dict]) -> dict[str, list[dict]]:
    """Allocated payment schedule per stay id, one query for the lot."""
    if not fins:
        return {}
    by_stay: dict[str, list] = {}
    for i in db.query(StayInstalment).filter(StayInstalment.tenant_id == tenant_id, StayInstalment.stay_id.in_(list(fins))).all():
        by_stay.setdefault(i.stay_id, []).append(i)
    return {sid: allocate_schedule(rows, fins[sid]["paid"]) for sid, rows in by_stay.items()}
