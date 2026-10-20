"""The Bookings agenda (layout B): segments, the month summary, the vehicle strip and the guest's WhatsApp window.

Segments partition every booking by status and by today's date in the workspace timezone:
  cancelled  status = cancelled
  staying    status = checked_in, or confirmed and the trip started before today and has not ended (check_out >= today)
  upcoming   confirmed and check-in today or later (a booking checking in today is still "upcoming" until checked in)
  past       status = checked_out, or confirmed and the trip ended before today

"Overdue" (one rule for the list filter, the money chip and the month summary): money is still owed on a booking that
is not cancelled, and either an instalment of its payment schedule is past due, or the trip has already started.

Money in the month summary is revenue (revenue.read); without it each figure is {"restricted": True}, never 0. The security
deposit is never part of any figure: it lives in stay_deposits, outside the total and the payment ledger.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.property import BlockedDate, Property, Stay
from app.models.stay_finance import StayAddOn, StayDeposit, StayInstalment, StayPayment
from app.services import booking_service as bsvc
from app.services import vehicle_pool

SEGMENTS = ("upcoming", "staying", "past", "cancelled")
WINDOW = timedelta(hours=24)
RESTRICTED = {"restricted": True}


def tenant_today(db: Session, tenant_id: str) -> date:
    from app.core.tenant_tz import get_tenant_now
    from app.models.tenant import Tenant
    tenant = db.get(Tenant, tenant_id)
    return get_tenant_now(tenant).date() if tenant else date.today()


# ── List filters ─────────────────────────────────────────────────────────────

def segment_clause(segment: str, today: date):
    if segment == "cancelled":
        return Stay.status == "cancelled"
    if segment == "staying":
        return or_(Stay.status == "checked_in",
                   and_(Stay.status == "confirmed", Stay.check_in < today, Stay.check_out >= today))
    if segment == "upcoming":
        return and_(Stay.status == "confirmed", Stay.check_in >= today)
    if segment == "past":
        return or_(Stay.status == "checked_out", and_(Stay.status == "confirmed", Stay.check_out < today))
    raise ValueError(f"segment must be one of {', '.join(SEGMENTS)}")


def segment_counts(q, today: date) -> dict[str, int]:
    """Bookings per segment for an already-filtered Query(Stay), in one query."""
    row = q.order_by(None).with_entities(
        *[func.coalesce(func.sum(case((segment_clause(s, today), 1), else_=0)), 0) for s in SEGMENTS]).one()
    return {s: int(n or 0) for s, n in zip(SEGMENTS, row)}


def owed_and_paid():
    """Correlated SQL for one booking's amount owed (stay charge + add-ons) and amount paid (payments - refunds)."""
    addons = (select(func.coalesce(func.sum(StayAddOn.quantity * StayAddOn.unit_price), 0))
              .where(StayAddOn.stay_id == Stay.id).correlate(Stay).scalar_subquery())
    signed = case((StayPayment.kind == "refund", -StayPayment.amount), else_=StayPayment.amount)
    paid = (select(func.coalesce(func.sum(signed), 0)).where(StayPayment.stay_id == Stay.id)
            .correlate(Stay).scalar_subquery())
    return func.coalesce(Stay.total_amount, 0) + addons, paid


def overdue_clause(today: date):
    owed, paid = owed_and_paid()
    fully_paid = (paid > 0) & (owed > 0) & (paid + 0.005 >= owed)
    later = aliased(StayInstalment)
    cum = (select(func.coalesce(func.sum(later.amount), 0))
           .where(later.stay_id == StayInstalment.stay_id, later.due_date <= StayInstalment.due_date)
           .correlate(StayInstalment).scalar_subquery())
    instalment_late = exists().where(StayInstalment.stay_id == Stay.id, StayInstalment.due_date < today,
                                     cum > paid + 0.005)
    return and_(owed > 0, ~fully_paid, Stay.status != "cancelled", or_(Stay.check_in < today, instalment_late))


def is_overdue(fin: dict, due: Optional[dict], check_in: date, status: str, today: date) -> bool:
    """Python twin of overdue_clause() for rows already loaded."""
    if status == "cancelled" or fin["outstanding"] <= 0:
        return False
    return bool(due and due["overdue"]) or check_in < today


# ── Extras for list rows and the booking page ────────────────────────────────

def trips_for(db: Session, tenant_id: str, stays) -> dict[str, str]:
    """What the trip is, as the lead recorded it (Inquiry.route_mentioned), per stay id. Nothing is invented."""
    from app.models.inquiry import Inquiry
    ids = {s.inquiry_id for s in stays if s.inquiry_id}
    if not ids:
        return {}
    routes = dict(db.query(Inquiry.id, Inquiry.route_mentioned)
                  .filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(list(ids))).all())
    return {s.id: routes[s.inquiry_id] for s in stays if s.inquiry_id and routes.get(s.inquiry_id)}


def deposits_for(db: Session, tenant_id: str, stay_ids: list[str]) -> dict[str, dict]:
    if not stay_ids:
        return {}
    return {d.stay_id: {"amount": float(d.amount), "status": d.status}
            for d in db.query(StayDeposit).filter(StayDeposit.tenant_id == tenant_id, StayDeposit.stay_id.in_(stay_ids)).all()}


def whatsapp_state(db: Session, tenant_id: str, guest_id: Optional[str]) -> dict:
    """The guest's open WhatsApp (Cloud API) conversation and whether the 24-hour reply window is open. Messages on the
    personal-WhatsApp mirror never open the business window, so they are left out."""
    out = {"conversation_id": None, "last_inbound_at": None, "window_open": False}
    if not guest_id:
        return out
    official = or_(Conversation.source.is_(None), Conversation.source != "personal_bridge")
    conv = (db.query(Conversation.id).filter(Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                                            Conversation.channel == ChannelType.WHATSAPP, Conversation.is_open.is_(True), official)
            .order_by(Conversation.last_message_at.desc()).first())
    last = (db.query(func.max(Message.created_at)).join(Conversation, Conversation.id == Message.conversation_id)
            .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                    Conversation.channel == ChannelType.WHATSAPP, official,
                    Message.direction == MessageDirection.INBOUND).scalar())
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    out["conversation_id"] = conv[0] if conv else None
    out["last_inbound_at"] = last.isoformat() if last else None
    out["window_open"] = bool(last and datetime.now(timezone.utc) - last <= WINDOW)
    return out


# ── Month summary ────────────────────────────────────────────────────────────

def _month_bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt


def _vehicles(db: Session, tenant_id: str) -> list[Property]:
    props = [p for p in db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).all()
             if not vehicle_pool.is_placeholder_name(p.name)]
    return sorted(props, key=lambda p: bsvc._natural(p.name))


def month_summary(db: Session, tenant_id: str, month: date, can_revenue: bool, today: Optional[date] = None) -> dict:
    """Bookings checking in during ``month`` (cancelled not counted): how many, per vehicle, and, with revenue.read,
    booked value / collected / still due / overdue."""
    today = today or tenant_today(db, tenant_id)
    start, end = _month_bounds(month)
    stays = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.status != "cancelled",
                                   Stay.check_in >= start, Stay.check_in < end).all())
    names = dict(db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id).all())
    per: dict[str, int] = {}
    for s in stays:
        per[s.property_id] = per.get(s.property_id, 0) + 1
    order = {p.id: i for i, p in enumerate(_vehicles(db, tenant_id))}
    by_vehicle = sorted(({"property_id": pid, "name": names.get(pid, "Unknown"), "count": n} for pid, n in per.items()),
                        key=lambda v: (order.get(v["property_id"], 999), v["name"]))
    out = {"month": start.strftime("%Y-%m"), "basis": "check_in", "today": today.isoformat(),
           "bookings": len(stays), "by_vehicle": by_vehicle}
    if not can_revenue:
        return {**out, "booked_value": RESTRICTED, "collected": RESTRICTED, "still_due": RESTRICTED, "overdue": RESTRICTED}
    fins = bsvc.financials_for(db, tenant_id, stays)
    schedules = bsvc.schedules_for(db, tenant_id, fins)
    booked = sum(f["total"] for f in fins.values())
    collected = sum(f["paid"] for f in fins.values())
    due = sum(f["outstanding"] for f in fins.values())
    overdue = sum(fins[s.id]["outstanding"] for s in stays
                  if is_overdue(fins[s.id], bsvc.next_due(schedules.get(s.id, [])), s.check_in, s.status, today))
    return {**out, "booked_value": round(booked, 2), "collected": round(collected, 2), "still_due": round(due, 2),
            "overdue": round(overdue, 2)}


# ── Vehicle strip ────────────────────────────────────────────────────────────

def occupancy(db: Session, tenant_id: str, days: int = 14, start: Optional[date] = None) -> dict:
    """Each vehicle's bookings (and other holds) over ``days`` days from today. A booking has ``due`` = money still owed."""
    today = tenant_today(db, tenant_id)
    start = start or today
    end = start + timedelta(days=days)            # exclusive
    vehicles = _vehicles(db, tenant_id)
    placeholders = [p for p in db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).all()
                    if vehicle_pool.is_placeholder_name(p.name)]
    pids = [p.id for p in vehicles + placeholders]
    stays = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id.in_(pids),
                                   Stay.status.in_(bsvc.ACTIVE_STATUSES), Stay.check_in < end, Stay.check_out >= start)
             .order_by(Stay.check_in).all()) if pids else []
    fins = bsvc.financials_for(db, tenant_id, stays)
    guests = dict(db.query(Guest.id, Guest.name).filter(Guest.tenant_id == tenant_id,
                                                        Guest.id.in_([s.guest_id for s in stays])).all()) if stays else {}
    blocks = (db.query(BlockedDate).filter(BlockedDate.tenant_id == tenant_id, BlockedDate.property_id.in_(pids),
                                           BlockedDate.is_active.is_(True), BlockedDate.blocked_from < end.isoformat(),
                                           BlockedDate.blocked_to > start.isoformat()).all()) if pids else []
    by_prop: dict[str, list] = {pid: [] for pid in pids}
    for s in stays:
        by_prop[s.property_id].append(s)

    def row(p: Property, slot: int) -> dict:
        own = by_prop.get(p.id, [])
        bookings = [{"booking_id": s.id, "guest_name": guests.get(s.guest_id) or "Guest", "check_in": s.check_in.isoformat(),
                     "check_out": s.check_out.isoformat(), "status": s.status, "due": fins[s.id]["outstanding"] > 0}
                    for s in own]

        def overlaps_booking(b: BlockedDate) -> bool:
            return any(s.check_in.isoformat() < b.blocked_to and b.blocked_from <= s.check_out.isoformat() for s in own)
        holds = [{"from": b.blocked_from, "to": b.blocked_to, "reason": b.reason}
                 for b in blocks if b.property_id == p.id and not overlaps_booking(b)]
        return {"property_id": p.id, "name": p.name, "slot": slot, "placeholder": vehicle_pool.is_placeholder_name(p.name),
                "bookings": bookings, "holds": holds}

    rows = [row(p, i % 2 + 1) for i, p in enumerate(vehicles)]
    # The "Unassigned" overflow shows only while it holds a real booking (same rule as the calendar).
    rows += [row(p, 0) for p in placeholders if by_prop.get(p.id)]
    return {"today": today.isoformat(), "from": start.isoformat(), "to": end.isoformat(), "days": days, "vehicles": rows}
