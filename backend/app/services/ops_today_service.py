"""The Ops "Today" screen (owner pick 25 Oct 2026: direction A "Needs you", unit cards on top for <= 6 units).

ONE read for the screen, so it never applies rules of its own:
  units  one card per vehicle: what it is doing, how ready, its biggest problem
  needs  only what needs a person, red first: open ops items (staff flags, issues) + what the trip files say
         (critical checks still open close to departure, a trip not accepted yet, extras waiting, money/deposit after return)
  day    today and tomorrow in time order: who leaves, who is away, who comes back
A day with nothing wrong returns an empty `needs`. Built for the caravan pack; other packs add their own needs here.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ops import OpsItem
from app.models.ops_files import OpsFile
from app.core.tenant_tz import get_tz
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.services import booking_agenda_service
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import ops_trip_service as trips
from app.services.vehicle_pool import is_placeholder_name

LIVE = trips.BEFORE_ROAD + ("on_trip", "returned")
_RED_SEVERITY = ("critical", "high")
_ORDER = {"red": 0, "amber": 1}


def _hours_until(d: date, hhmm: Optional[str], now: datetime, tz) -> float:
    """Hours from now to the booking's start (its local pickup time; noon when none is set)."""
    try:
        t = time(int(hhmm[:2]), int(hhmm[3:5])) if hhmm else time(12, 0)
    except (TypeError, ValueError):
        t = time(12, 0)
    return (datetime.combine(d, t, tzinfo=tz) - now).total_seconds() / 3600


def _need(level, unit, title, detail, file_id=None, action="open_file", item_id=None, key=None) -> dict:
    return {"key": key or f"{action}:{file_id or item_id}:{title}", "level": level, "unit": unit, "title": title,
            "detail": detail, "file_id": file_id, "item_id": item_id, "action": action}


def _file_needs(db: Session, f: OpsFile, stay: Stay, unit: str, now: datetime, tz) -> list[dict]:
    out: list[dict] = []
    who = (stay.guest.name if stay.guest is not None else None) or "Guest"
    hours = _hours_until(stay.check_in, stay.check_in_time, now, tz)
    if f.state in trips.BEFORE_ROAD:
        if f.accepted_at is None and hours < 24 * 7:
            out.append(_need("amber", unit, f"Accept {who}'s trip", "Set the route and km included.", f.id))
        g = trips.gate(trips.readiness_items(db, f))
        if g["blocking"] and hours < 72:
            n = len(g["blocking"])
            out.append(_need("red" if hours < 24 else "amber", unit, f"{n} check{'s' if n != 1 else ''} still open",
                             f"Leaves in {max(0, round(hours))} h. Dispatch stays blocked until they are green.", f.id))
        if f.state == "dispatch_ready" and hours < 24:
            out.append(_need("amber", unit, "Ready to dispatch", f"{who} leaves in {max(0, round(hours))} h. Tap Dispatch.", f.id))
    a = money.account(db, f)
    if a["extras_waiting"]:
        n = a["extras_waiting"]
        out.append(_need("amber", unit, f"{n} extra{'s' if n != 1 else ''} waiting for you", "Approve or remove before billing.", f.id))
    if f.state == "returned":
        dep = a["deposit"]
        back_h = (now - f.returned_at).total_seconds() / 3600 if f.returned_at else 0
        if dep is not None and dep["status"] == "held":
            out.append(_need("red" if back_h > 48 else "amber", unit, f"Refund deposit Rs {dep['amount']:,}",
                             f"{who}'s trip ended. Due within 48 hours of return.", f.id))
        if a["outstanding"] > 0:
            out.append(_need("amber", unit, f"Collect Rs {a['outstanding']:,}", f"{who}'s balance after the trip.", f.id))
        if (dep is None or dep["status"] != "held") and a["outstanding"] <= 0:
            out.append(_need("amber", unit, trips.stage(db, f)["next"] or "Close the trip", f"{who}'s trip is back.", f.id))
    return out


def build(db: Session, tenant_id: str, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tenant = db.get(Tenant, tenant_id)
    tz = get_tz(tenant) if tenant else timezone.utc
    today = booking_agenda_service.tenant_today(db, tenant_id)
    trips.sync_files(db, tenant_id, today)          # a new booking shows up here without waiting for a job
    db.flush()
    props = [p for p in db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
             .order_by(Property.name) if not is_placeholder_name(p.name)]
    names = {p.id: p.name for p in props}
    rows = (db.query(OpsFile, Stay).join(Stay, Stay.id == OpsFile.stay_id)
            .filter(OpsFile.tenant_id == tenant_id, OpsFile.state.in_(LIVE)).order_by(Stay.check_in).all())
    pack = packs.pack_for_business_type(tenant.business_type if tenant else None) or "caravan_rv"
    spec = packs.get(pack)

    needs: list[dict] = []
    file_needs: dict[str, list[dict]] = {}
    for f, stay in rows:
        fn = _file_needs(db, f, stay, names.get(stay.property_id, "Trip"), now, tz)
        file_needs[f.id] = fn
        needs += fn
    by_stay = {stay.id: f for f, stay in rows}
    for it in (db.query(OpsItem).filter(OpsItem.tenant_id == tenant_id, OpsItem.status.in_(("open", "acknowledged")))
               .order_by(OpsItem.created_at.desc()).limit(50)):
        f = by_stay.get(it.stay_id) if it.stay_id else None
        lvl = "red" if it.severity in _RED_SEVERITY else "amber"
        title = it.title.split(": ", 1)[-1]                       # the unit is shown apart; "Ratha 1: crew ..." -> "Crew ..."
        n = _need(lvl, names.get(it.property_id, "Ops"), title[:1].upper() + title[1:], it.summary or "", f.id if f else None,
                  action="resolve_item", item_id=it.id, key=f"item:{it.id}")
        needs.append(n)
        if f is not None:
            file_needs.setdefault(f.id, []).append(n)
    needs.sort(key=lambda n: _ORDER[n["level"]])

    units = []
    for p in props:
        mine = [(f, s) for f, s in rows if s.property_id == p.id]
        on_road = next(((f, s) for f, s in mine if f.state == "on_trip"), None)
        back = next(((f, s) for f, s in mine if f.state == "returned"), None)
        nxt = next(((f, s) for f, s in mine if f.state in trips.BEFORE_ROAD), None)
        cur = on_road or back or nxt
        if cur is None:
            units.append({"property_id": p.id, "name": p.name, "tone": "idle", "status": "Free", "line": "No trip coming up",
                          "problem": None, "file_id": None, "ready_pct": None})
            continue
        f, s = cur
        fn = file_needs.get(f.id, [])
        tone = "red" if any(n["level"] == "red" for n in fn) else "amber" if fn else "ok"
        g = trips.gate(trips.readiness_items(db, f))
        who = (s.guest.name if s.guest is not None else None) or "Guest"
        status, line = {
            "on_trip": ("On the road", f"{who} · back {s.check_out.strftime('%a %d %b')}"),
            "returned": ("Back, to settle", f"{who} · returned"),
        }.get(f.state, ("Getting ready", f"{who} · leaves {s.check_in.strftime('%a %d %b')}"
                        + (f" {s.check_in_time}" if s.check_in_time else "")))
        units.append({"property_id": p.id, "name": p.name, "tone": tone, "status": status, "line": line,
                      "problem": fn[0]["title"] if fn else None, "file_id": f.id,
                      "ready_pct": round(100 * g["green"] / g["total"]) if g["total"] and f.state in trips.BEFORE_ROAD else None})

    day = []
    horizon = today + timedelta(days=1)
    for f, s in rows:
        unit = names.get(s.property_id, "Trip")
        who = (s.guest.name if s.guest is not None else None) or "Guest"
        if f.state == "on_trip":
            day.append({"date": today.isoformat(), "time": None, "now": True, "what": f"{unit} on the road",
                        "sub": who, "file_id": f.id, "tone": "red" if any(n["level"] == "red" for n in file_needs.get(f.id, [])) else "ok"})
            if s.check_out <= horizon:
                day.append({"date": s.check_out.isoformat(), "time": s.check_out_time, "now": False, "what": f"{unit} comes back",
                            "sub": f"{who} · return check + odometer photo", "file_id": f.id, "tone": "idle"})
        elif f.state in trips.BEFORE_ROAD and today <= s.check_in <= horizon:
            g = trips.gate(trips.readiness_items(db, f))
            day.append({"date": s.check_in.isoformat(), "time": s.check_in_time, "now": False, "what": f"{unit} leaves",
                        "sub": f"{who} · {g['green']} of {g['total']} checks green", "file_id": f.id,
                        "tone": "ok" if g["ready"] else "amber"})
    day.sort(key=lambda e: (not e["now"], e["date"], e["time"] or "99:99"))
    counts = {"leaving": sum(1 for f, s in rows if f.state in trips.BEFORE_ROAD and today <= s.check_in <= horizon),
              "away": sum(1 for f, _ in rows if f.state == "on_trip"),
              "back": sum(1 for f, s in rows if (f.state == "on_trip" and s.check_out <= horizon) or f.state == "returned")}
    return {"date": today.isoformat(), "pack": pack, "unit_word": spec["unit_word"], "file_word": spec["file_word"],
            "units": units, "needs": needs, "day": day, "counts": counts}
