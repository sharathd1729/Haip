"""Is a caravan free from D1 to D2, which one, and what are the nearest free dates? One answer for the sales agent.

There is no second availability engine here. Every vehicle is checked with booking_service.find_conflicts, the same rule
POST /bookings, the calendar and a paid quote link use, so the answer counts exactly what they count:

  * bookings that are confirmed or checked in (a cancelled booking frees its dates);
  * calendar blocks, whatever made them: maintenance, personal use, a block imported from an iCal / Google Calendar link
    (reason ``offline_booking``), a manual "other" block;
  * vehicles sharing a calendar (vehicle_pool): bookings that have no vehicle yet use up one of the vehicles that day.

Dates are noon to noon: a stay occupies [check_in, check_out), so a trip ending on the 12th and one starting on the 12th do not
clash; a same-day trip (check_in == check_out) occupies its day. The "Unassigned" placeholder is never offered as a vehicle.

A guest is never told WHAT holds a date (whose booking, which block); the reasons here are for staff and for the prompt's
"not open" wording only. Read-only.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.property import Property
from app.services import booking_service, vehicle_pool

log = structlog.get_logger()

MAX_SHIFT_DAYS = 14            # how far either side the nearest free dates are looked for
MAX_ALTERNATIVES = 3


def _vehicles(db: Session, tenant_id: str, vehicle_ids: Optional[list[str]] = None) -> list[Property]:
    q = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    if vehicle_ids:
        q = q.filter(Property.id.in_(list(vehicle_ids)))
    return sorted((p for p in q.all() if not vehicle_pool.is_placeholder_name(p.name)), key=lambda p: booking_service._natural(p.name))


def _status(conflicts: list[dict]) -> str:
    """The first conflict, in words a member of staff understands. Never shown to a guest beyond "not open"."""
    c = conflicts[0]
    if c["type"] == "booking":
        return "booked"
    if c["type"] == "unassigned_bookings":
        return "held_for_unassigned_booking"
    reason = (c.get("reason") or "").lower()
    if reason == "maintenance":
        return "maintenance"
    if reason == "offline_booking":
        return "booked_elsewhere"            # an iCal / Google Calendar import, or a booking taken outside HAIP
    return "blocked"


def _free_vehicle(db: Session, tenant_id: str, vehicles: list[Property], ci: date, co: date) -> Optional[Property]:
    for v in vehicles:
        if not booking_service.find_conflicts(db, tenant_id, v.id, ci, co):
            return v
    return None


def check(db: Session, tenant_id: str, check_in: date, check_out: date, adults: int = 1, children: int = 0,
          vehicle_ids: Optional[list[str]] = None, today: Optional[date] = None, alternatives: int = MAX_ALTERNATIVES) -> dict:
    """{available, vehicle, vehicles[], alternatives[], nights, check_in, check_out, window, reason?}.

    ``vehicle`` is the vehicle a booking made now would get (the first free one by name, as pick_free_property assigns);
    ``alternatives`` are the nearest free windows of the same length (closest first, later before earlier on a tie, never in the
    past), only when the requested dates are not free for this party. ``vehicle_ids`` limits the check to a package's vehicles.
    """
    today = today or date.today()
    nights = (check_out - check_in).days
    out: dict = {"check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "nights": max(nights, 0),
                 "window": "noon to noon", "available": False, "vehicle": None, "vehicles": [], "alternatives": []}
    if nights < 0:
        out["reason"] = "check_out_before_check_in"
        return out
    if check_in < today:
        out["reason"] = "in_the_past"
        return out
    fleet = _vehicles(db, tenant_id, vehicle_ids)
    if not fleet:
        out["reason"] = "no_vehicles"
        return out
    fits = [v for v in fleet if not (v.max_adults and adults > v.max_adults)]
    for v in fleet:
        row = {"property_id": v.id, "property_name": v.name, "max_adults": v.max_adults, "free": False}
        if v not in fits:
            row["status"] = "too_small"
        else:
            conflicts = booking_service.find_conflicts(db, tenant_id, v.id, check_in, check_out)
            row["status"] = _status(conflicts) if conflicts else "free"
            row["free"] = not conflicts
        out["vehicles"].append(row)
    free = [r for r in out["vehicles"] if r["free"]]
    if free:
        out["available"] = True
        out["vehicle"] = {"id": free[0]["property_id"], "name": free[0]["property_name"]}
        return out
    out["reason"] = "too_small" if not fits else "taken"
    if fits and alternatives > 0:
        out["alternatives"] = nearest_free(db, tenant_id, fits, check_in, nights, today, alternatives)
    return out


def nearest_free(db: Session, tenant_id: str, vehicles: list[Property], check_in: date, nights: int, today: date,
                 limit: int = MAX_ALTERNATIVES) -> list[dict]:
    """The closest start dates (same number of nights) on which one of these vehicles is free."""
    found: list[dict] = []
    for shift in range(1, MAX_SHIFT_DAYS + 1):
        for sign in (1, -1):
            start = check_in + timedelta(days=shift * sign)
            if start < today:
                continue
            end = start + timedelta(days=nights)
            v = _free_vehicle(db, tenant_id, vehicles, start, end)
            if v is not None:
                found.append({"check_in": start.isoformat(), "check_out": end.isoformat(), "shift_days": shift * sign,
                              "vehicle": {"id": v.id, "name": v.name}})
                if len(found) >= limit:
                    return found
    return found


def as_check_fact(result: dict, adults: int, children: int) -> dict:
    """The ``check_availability`` grounded fact the concierge prompt and its guards already read, built from ``check``.

    Each vehicle is ``available`` only when it is free and fits the party; a vehicle that is not free says ``unavailable`` (the
    prompt words it "booked or unavailable") and one that is too small says ``over_capacity``. No prices: those come from the
    package quote alone."""
    rows = []
    for v in result.get("vehicles") or []:
        reason = None if v["free"] else ("over_capacity" if v["status"] == "too_small" else "unavailable")
        rows.append({"property_id": v["property_id"], "property_name": v["property_name"], "available": bool(v["free"]),
                     "reason": reason, "max_adults": v.get("max_adults"), "nights": result["nights"]})
    fact = {"tool": "check_availability", "source": "calendar",
            "args": {"checkin": result["check_in"], "checkout": result["check_out"], "adults": adults, "children": children},
            "result": rows, "alternatives": result.get("alternatives") or []}
    if result.get("reason") in ("no_vehicles",):
        fact["lookup_failed"] = True
    return fact
