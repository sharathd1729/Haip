"""Vehicles that share one booking calendar, handled the way a hotel handles room types.

Ratha has two caravans. A booking taken without saying which one sits on a placeholder "Unassigned" property (the same one
legacy bookings use) and is given a real vehicle at check-in. Until then it still uses up one of the two, so a day is only
bookable on a vehicle when, after counting the unassigned bookings, at least one vehicle is still free that day.

The pool is the set of vehicles listed on a shared Google Calendar link (``ICalFeedVehicle``). A property that is in no pool
is never affected by any of this.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ical_feed import ICalFeed, ICalFeedVehicle
from app.models.property import BlockedDate, Property, Stay

ACTIVE = ("confirmed", "checked_in")
MAX_DAYS = 92                       # longest window examined in one call


def is_placeholder_name(name: Optional[str]) -> bool:
    return (name or "").strip().lower().startswith("unassigned")


def placeholder_ids(db: Session, tenant_id: str) -> list[str]:
    rows = db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id).all()
    return [pid for pid, name in rows if is_placeholder_name(name)]


def placeholder_property(db: Session, tenant_id: str, prefer_id: Optional[str] = None) -> Property:
    """The tenant's "Unassigned" property (the feed's own if it is one), created on first use."""
    props = [p for p in db.query(Property).filter(Property.tenant_id == tenant_id).all() if is_placeholder_name(p.name)]
    if prefer_id:
        for p in props:
            if p.id == prefer_id:
                return p
    if props:
        return sorted(props, key=lambda p: (not p.is_active, p.name))[0]
    prop = Property(tenant_id=tenant_id, name="Unassigned (vehicle not chosen yet)", slug="unassigned-vehicle-not-chosen",
                    type="caravan", is_active=True)
    db.add(prop)
    db.flush()
    return prop


def pool_of(db: Session, tenant_id: str, property_id: str) -> list[str]:
    """Every vehicle that shares a calendar with this one (including itself); empty when it shares none."""
    feed_ids = [r[0] for r in db.query(ICalFeedVehicle.feed_id).join(ICalFeed, ICalFeed.id == ICalFeedVehicle.feed_id).filter(
        ICalFeedVehicle.tenant_id == tenant_id, ICalFeedVehicle.property_id == property_id, ICalFeed.is_active.is_(True)).all()]
    if not feed_ids:
        return []
    ids = {r[0] for r in db.query(ICalFeedVehicle.property_id).filter(
        ICalFeedVehicle.tenant_id == tenant_id, ICalFeedVehicle.feed_id.in_(feed_ids)).all()}
    return sorted(ids)


def _days(lo: date, hi: date) -> list[date]:
    hi = max(hi, lo + timedelta(days=1))                # a same-day stay still uses its day
    return [lo + timedelta(days=i) for i in range(min((hi - lo).days, MAX_DAYS))]


def _occupancy(db: Session, tenant_id: str, pool: list[str], days: list[date], exclude_stay_id: Optional[str]):
    """({day: set of pool vehicles in use}, {day: unassigned bookings}) for the days given."""
    lo, hi = days[0].isoformat(), (days[-1] + timedelta(days=1)).isoformat()
    in_use: dict[date, set] = {d: set() for d in days}
    unassigned: dict[date, int] = {d: 0 for d in days}
    holders = placeholder_ids(db, tenant_id)
    q = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.status.in_(ACTIVE),
                              Stay.property_id.in_(pool + holders), Stay.check_in < hi, Stay.check_out > lo)
    if exclude_stay_id:
        q = q.filter(Stay.id != exclude_stay_id)
    for s in q.all():
        for d in _days(s.check_in, s.check_out):
            if d in in_use:
                if s.property_id in holders:
                    unassigned[d] += 1
                else:
                    in_use[d].add(s.property_id)
    for b in db.query(BlockedDate).filter(BlockedDate.tenant_id == tenant_id, BlockedDate.property_id.in_(pool),
                                          BlockedDate.is_active.is_(True), BlockedDate.blocked_from < hi, BlockedDate.blocked_to > lo).all():
        for d in _days(date.fromisoformat(b.blocked_from), date.fromisoformat(b.blocked_to)):
            if d in in_use:
                in_use[d].add(b.property_id)
    return in_use, unassigned


def shortage_days(db: Session, tenant_id: str, property_id: str, check_in: date, check_out: date,
                  exclude_stay_id: Optional[str] = None) -> list[str]:
    """Days in [check_in, check_out) on which this vehicle is free but taking it would leave too few vehicles for the
    bookings that have no vehicle yet. Empty when the vehicle is in no pool."""
    pool = pool_of(db, tenant_id, property_id)
    if property_id not in pool:
        return []
    days = _days(check_in, check_out)
    in_use, unassigned = _occupancy(db, tenant_id, pool, days, exclude_stay_id)
    out = []
    for d in days:
        free = [p for p in pool if p not in in_use[d]]
        if property_id in free and len(free) - unassigned[d] < 1:
            out.append(d.isoformat())
    return out


def over_capacity_days(db: Session, tenant_id: str, property_ids: list[str], lo: date, hi: date) -> list[str]:
    """Days where bookings without a vehicle outnumber the vehicles still free (an overbooking nobody has noticed yet)."""
    pool = sorted(set(property_ids))
    if not pool:
        return []
    days = _days(lo, hi)
    in_use, unassigned = _occupancy(db, tenant_id, pool, days, None)
    return [d.isoformat() for d in days if unassigned[d] > len([p for p in pool if p not in in_use[d]])]
