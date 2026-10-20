"""Owner dashboard (layout A, 19 Oct 2026): the six "Needs attention" cards and the check-ins / check-outs list.

Five of the six cards are read straight off the shared work queue (work_queue_service.build, read ONCE per request by the
Business Overview); nothing here re-derives who is waiting:

  not_replying   queue kind ``no_reply`` (D-23)
  not_called     queue items flagged ``not_called``
  missed_calls   queue kind ``callback``
  followups      queue follow-ups flagged ``open_lead`` (open enquiry in a valid stage)
  at_risk        queue items flagged ``at_risk``
  owing          the one card that is about BOOKINGS, not people: live bookings checking in within 30 days that still owe
                 money (booking_service.financials_for / schedules_for). Needs bookings.read (otherwise ``{"restricted": true}``);
                 the rupee amounts need revenue.read as well (otherwise ``None``, the count still shows).

Each card says how many, why (one line), the first three names with how long they have waited, the worst severity among its
items (the queue's SLA_MINUTES rule) and where to open the full list. Contacts without a phone number are never counted (D-22).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.property import Property, Stay
from app.services import booking_service
from app.services.business_overview_common import Params, _linked_stay_ids

OWING_DAYS = 30
TOP = 3
WINDOWS = (3, 7, 15, 30)
MOVEMENT_CAP = 200
_RANK = {"fresh": 0, "late": 1, "urgent": 2, "critical": 3, "stale": 0}

CARDS = (
    # key, title, reason, href, how to pick the items
    ("not_replying", "Not replying", "We wrote last and they have been silent for 24 h or more",
     "/dashboard/my-day?kind=no_reply", lambda i: i["kind"] == "no_reply"),
    ("not_called", "Not called yet", "Shared a phone number; nobody has called them",
     "/dashboard/my-day?flag=not_called", lambda i: "not_called" in i.get("flags", [])),
    ("missed_calls", "Missed calls not returned", "They called, nobody has called back yet",
     "/dashboard/my-day?kind=callback", lambda i: i["kind"] == "callback"),
    ("followups", "Follow-ups overdue", "Due now or overdue, on active leads only; lost and unqualified are left out",
     "/dashboard/my-day?kind=followup&flag=open_lead", lambda i: i["kind"] == "followup" and "open_lead" in i.get("flags", [])),
    ("at_risk", "Promising leads at risk", "Warm, check-in in the next 30 days, quiet for 48 h",
     "/dashboard/my-day?flag=at_risk", lambda i: "at_risk" in i.get("flags", [])),
)


def _worst(items: list[dict]) -> str:
    worst = "fresh"
    for i in items:
        if _RANK.get(i.get("severity", "fresh"), 0) > _RANK[worst]:
            worst = i["severity"]
    return worst


def _people_card(key: str, title: str, reason: str, href: str, items: list[dict], count: int) -> dict:
    seen, top = set(), []
    for i in items:
        who = i.get("guest_id") or i.get("title")
        if who in seen:
            continue
        seen.add(who)
        if len(top) < TOP:
            top.append({"name": i.get("title") or "Lead", "detail": i.get("detail") or "", "since": i.get("since"),
                        "facts": i.get("facts") or [], "href": i.get("href")})
    return {"key": key, "title": title, "reason": reason, "count": count, "people": top, "href": href,
            "severity": _worst(items), "restricted": False}


def attention_cards(work: dict, owing: Optional[dict]) -> list[dict]:
    """The six cards, in the order of the approved layout. ``owing`` is None when the viewer may not read bookings."""
    # The cold tail (severity "stale") is left out, as on Home and in the nav badge; My day still lists it at the bottom.
    items = [i for i in work.get("items", []) if i.get("severity") != "stale"]
    out = []
    for key, title, reason, href, pick in CARDS:
        mine = [i for i in items if pick(i)]
        count = len(mine) if key == "followups" else len({i.get("guest_id") or i.get("title") for i in mine})
        out.append(_people_card(key, title, reason, href, mine, count))
    if owing is None:
        out.append({"key": "owing", "title": "Bookings still owing money", "restricted": True})
    else:
        out.append(owing)
    return out


# ── bookings still owing money ───────────────────────────────────────────────────────────────────────────────

def _live_stays(db: Session, p: Params, today: date, until: date):
    q = (db.query(Stay).options(joinedload(Stay.guest))
         .filter(Stay.tenant_id == p.tid, Stay.status.in_(("confirmed", "checked_in")), Stay.check_out >= today,
                 Stay.check_in <= until))
    if p.property_id:
        q = q.filter(Stay.property_id == p.property_id)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        q = q.filter(Stay.id.in_(scoped))
    return q.order_by(Stay.check_in.asc()).limit(MOVEMENT_CAP).all()


def owing_card(db: Session, p: Params, today: date) -> dict:
    """Live bookings (confirmed or checked in, not yet checked out) with a check-in in the next 30 days that still owe money:
    how many, the total still owed, and the first three by due date (overdue first)."""
    stays = _live_stays(db, p, today, today + timedelta(days=OWING_DAYS))
    fins = booking_service.financials_for(db, p.tid, stays)
    schedules = booking_service.schedules_for(db, p.tid, fins)
    rows = []
    for s in stays:
        fin = fins[s.id]
        if fin["total"] <= 0 or fin["outstanding"] <= 0.005:
            continue
        due = booking_service.next_due(schedules.get(s.id, []))
        rows.append({"stay": s, "outstanding": round(fin["outstanding"], 2), "due_date": due["due_date"] if due else None,
                     "overdue": bool(due and due["overdue"])})
    rows.sort(key=lambda r: (not r["overdue"], str(r["due_date"] or r["stay"].check_in)))
    money = p.can_revenue
    people = [{"name": (r["stay"].guest.name if r["stay"].guest and r["stay"].guest.name else "Guest"),
               "amount": r["outstanding"] if money else None, "due_date": str(r["due_date"]) if r["due_date"] else None, "overdue": r["overdue"],
               "check_in": r["stay"].check_in.isoformat(), "href": f"/dashboard/bookings/{r['stay'].id}"} for r in rows[:TOP]]
    return {"key": "owing", "title": "Bookings still owing money", "reason": "Check-in in the next 30 days",
            "count": len(rows), "amount": round(sum(r["outstanding"] for r in rows), 2) if money else None, "people": people,
            "href": "/dashboard/bookings?quick=due", "severity": "urgent" if any(r["overdue"] for r in rows) else "fresh",
            "restricted": False}


# ── check-ins and check-outs from today ──────────────────────────────────────────────────────────────────────

def _trip(stay: Stay) -> str:
    nights = (stay.check_out - stay.check_in).days
    bits = [f"{nights} night{'s' if nights != 1 else ''}" if nights > 0 else "day trip"]
    if stay.occasion:
        bits.append(str(stay.occasion))
    return " · ".join(bits)


def movements(db: Session, p: Params, today: date, window_days: int) -> dict:
    """Check-ins and check-outs of live bookings in [today, today + window - 1], soonest first. No amounts."""
    until = today + timedelta(days=window_days - 1)
    q = (db.query(Stay).options(joinedload(Stay.guest))
         .filter(Stay.tenant_id == p.tid, Stay.status.in_(("confirmed", "checked_in")),
                 or_(Stay.check_in.between(today, until), Stay.check_out.between(today, until))))
    if p.property_id:
        q = q.filter(Stay.property_id == p.property_id)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        q = q.filter(Stay.id.in_(scoped))
    stays = q.limit(MOVEMENT_CAP + 1).all()
    names = dict(db.query(Property.id, Property.name).filter(Property.tenant_id == p.tid,
                                                            Property.id.in_({s.property_id for s in stays} or {""})).all())
    out = []
    for s in stays[:MOVEMENT_CAP]:
        base = {"guest": s.guest.name if s.guest and s.guest.name else "Guest", "property": names.get(s.property_id, ""),
                "trip": _trip(s), "href": f"/dashboard/bookings/{s.id}", "status": s.status}
        if today <= s.check_in <= until:
            out.append({**base, "kind": "check_in", "date": s.check_in.isoformat(), "days_from_today": (s.check_in - today).days})
        if today <= s.check_out <= until:
            out.append({**base, "kind": "check_out", "date": s.check_out.isoformat(), "days_from_today": (s.check_out - today).days})
    out.sort(key=lambda r: (r["date"], r["kind"] != "check_out", r["guest"]))
    return {"restricted": False, "window_days": window_days, "from": today.isoformat(), "to": until.isoformat(),
            "check_ins": sum(1 for r in out if r["kind"] == "check_in"), "check_outs": sum(1 for r in out if r["kind"] == "check_out"),
            "items": out, "truncated": len(stays) > MOVEMENT_CAP}
