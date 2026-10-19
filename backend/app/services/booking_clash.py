"""Is each caravan free for these dates AND times, and if not, why -- in words a member of staff reads once and acts on.

The rule itself lives in booking_service (find_conflicts / turnarounds / pick_free_property). This module only turns it into
per-vehicle states for the new-booking flow and the plain-words 409 that POST /bookings and POST /bookings/compose answer with:

  free     nothing overlaps
  tight    nothing overlaps, but another trip on this vehicle ends or starts less than 2 hours away (a warning: cleaning time)
  booked   a booking or calendar block overlaps (by time when both bookings have times, else by date)

Staff-facing only: names the other guest. Read-only.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.property import Property
from app.services import booking_service as bsvc
from app.services import vehicle_pool


def day(d: date) -> str:
    """"Sun 1 Nov"."""
    return f"{d:%a} {d.day} {d:%b}"


def clock(t: Optional[str]) -> str:
    """"07:00" -> "7:00 am", "12:00" -> "12:00 pm". Empty when there is no time."""
    if not t or len(t) < 4:
        return ""
    h, m = int(t[:2]), t[3:5]
    return f"{h % 12 or 12}:{m} {'pm' if h >= 12 else 'am'}"


def span(a: date, b: date) -> str:
    """"21–22 Oct", "30 Oct–1 Nov", "21 Oct" for a day trip."""
    if a == b:
        return f"{a.day} {a:%b}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {b:%b}"
    return f"{a.day} {a:%b}–{b.day} {b:%b}"


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _what(name: str, c: dict, check_in: date, check_out: date) -> str:
    """What holds the vehicle, in one clause."""
    a, b = _d(c["from"]), _d(c["to"])
    if c["type"] == "booking":
        who = c.get("guest") or "another guest"
        if c.get("to_time") and b == check_in and a < check_in:
            return f"{name} is out with {who} until {clock(c['to_time'])} on {day(b)}"
        if c.get("from_time") and a == check_out and b > check_out:
            return f"{name} leaves with {who} at {clock(c['from_time'])} on {day(a)}"
        return f"{name} is booked {span(a, b)} ({who})"
    if c["type"] == "block":
        reason = (c.get("reason") or "").lower()
        why = {"maintenance": "for maintenance", "offline_booking": "by a booking outside HAIP"}.get(reason, "on the calendar")
        return f"{name} is blocked {span(a, b)} {why}"
    return f"{name} is needed on {span(a, b)} for bookings that have no caravan yet"


def clash_message(name: str, conflict: dict, check_in: date, check_out: date, others_free: list[str], others: list[str]) -> str:
    """"Ratha 2 is booked 21–22 Oct (Manisha Rao). Pick Ratha 1 or other dates." """
    what = _what(name, conflict, check_in, check_out)
    if others_free:
        return f"{what}. Pick {others_free[0]} or other dates."
    if others:
        return f"{what}. {' and '.join(others)} {'is' if len(others) == 1 else 'are'} taken too, so pick other dates."
    return f"{what}. Pick other dates."


def tight_message(name: str, t: dict) -> str:
    who = (t.get("guest") or "Another guest").split(" ")[0]
    if t.get("returns_before"):
        return (f"{who} returns {name} at {clock(t['to_time'])} on {day(_d(t['to']))}. "
                "Less than 2 hours to clean before this pickup.")
    return f"{who} picks up {name} at {clock(t['from_time'])} on {day(_d(t['from']))}. Less than 2 hours after this return."


def vehicles(db: Session, tenant_id: str) -> list[Property]:
    q = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    return sorted((p for p in q.all() if not vehicle_pool.is_placeholder_name(p.name)), key=lambda p: bsvc._natural(p.name))


def states(db: Session, tenant_id: str, check_in: date, check_out: date, check_in_time: Optional[str], check_out_time: Optional[str],
           exclude_stay_id: Optional[str] = None) -> dict:
    """{"vehicles": [{property_id, name, state, message, other}], "auto": {property_id, name, state} | None, "message": str|None}.
    ``auto`` is the vehicle "First free caravan" would hold (pick_free_property's choice); ``message`` says why there is none."""
    fleet = vehicles(db, tenant_id)
    raw = []
    for v in fleet:
        conflicts = bsvc.find_conflicts(db, tenant_id, v.id, check_in, check_out, exclude_stay_id,
                                        check_in_time=check_in_time, check_out_time=check_out_time)
        tight = [] if conflicts else bsvc.turnarounds(db, tenant_id, v.id, check_in, check_out, check_in_time, check_out_time,
                                                      exclude_stay_id)
        raw.append((v, conflicts, tight))
    free_names = [v.name for v, c, _ in raw if not c]
    rows = []
    for v, conflicts, tight in raw:
        if conflicts:
            others = [x.name for x, _, _ in raw if x.id != v.id]
            row = {"property_id": v.id, "name": v.name, "state": "booked", "other": conflicts[0],
                   "message": clash_message(v.name, conflicts[0], check_in, check_out, [n for n in free_names if n != v.name], others)}
        elif tight:
            row = {"property_id": v.id, "name": v.name, "state": "tight", "other": tight[0], "message": tight_message(v.name, tight[0])}
        else:
            row = {"property_id": v.id, "name": v.name, "state": "free", "other": None, "message": None}
        rows.append(row)
    auto = next((r for r in rows if r["state"] == "free"), None) or next((r for r in rows if r["state"] == "tight"), None)
    message = None
    if auto is None:
        if not rows:
            message = "There is no caravan to book. Add one under Portfolio first."
        else:
            parts = [f"{r['name']}: {_holder(r['other'])}" for r in rows]
            message = f"{'Both caravans are' if len(rows) == 2 else 'Every caravan is'} booked on these dates ({'; '.join(parts)}). Try other dates."
    return {"vehicles": rows, "auto": {k: auto[k] for k in ("property_id", "name", "state")} if auto else None, "message": message}


def _holder(c: dict) -> str:
    rng = span(_d(c["from"]), _d(c["to"]))
    if c["type"] == "booking":
        return f"{c.get('guest') or 'a booking'} {rng}"
    return f"blocked {rng}" if c["type"] == "block" else f"held {rng}"


def refuse_message(db: Session, tenant_id: str, prop: Property, conflicts: list[dict], check_in: date, check_out: date,
                   check_in_time: Optional[str], check_out_time: Optional[str]) -> str:
    """The 409 text when a booking is put on a vehicle that is taken."""
    others = [v for v in vehicles(db, tenant_id) if v.id != prop.id]
    free = [v.name for v in others if not bsvc.find_conflicts(db, tenant_id, v.id, check_in, check_out,
                                                               check_in_time=check_in_time, check_out_time=check_out_time)]
    return clash_message(prop.name, conflicts[0], check_in, check_out, free, [v.name for v in others])
