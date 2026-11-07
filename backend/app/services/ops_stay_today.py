"""Ops Today for villa businesses (phase 4): the same screen and shape as ops_today_service (units, needs red first, today
and tomorrow), with the villa pack's rules. ops_today_service.build hands villa tenants here.

needs: open ops items (staff flags), arrival < 72 h with critical checks open (red < 24 h), ready to welcome, no caretaker
close to arrival, today's meals the cook has not confirmed, a mid-stay clean due, the check-out inspection (damage = red),
the deposit to decide (red 48 h after check-out), the balance, and the next settle step.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tz
from app.models.ops import OpsItem
from app.services.ops_escalation_service import _aware as esc_aware
from app.models.ops_files import OpsFile, OpsJob
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.services import booking_agenda_service, ops_stay_meals
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import ops_stay_service as stays
from app.services import ops_trip_service as trips
from app.services.ops_today_service import _ORDER, _RED_SEVERITY, HELD_FOR_LATER, _hours_until, _need
from app.services.vehicle_pool import is_placeholder_name


def arrives_text(hours: float) -> str:
    if hours >= 1:
        return f"Arrives in {round(hours)} h"
    return "Arriving now" if hours > -1 else f"Was due {round(-hours)} h ago"


def _file_needs(db: Session, f: OpsFile, stay: Stay, unit: str, now: datetime, tz, today) -> list[dict]:
    out: list[dict] = []
    who = (stay.guest.name if stay.guest is not None else None) or "Guest"
    hours = _hours_until(stay.check_in, stay.check_in_time, now, tz)
    d = money.details(f)
    if f.state in stays.BEFORE_WELCOME:
        g = trips.gate(trips.readiness_items(db, f))
        if g["blocking"] and hours < 72:
            n = len(g["blocking"])
            out.append(
                _need(
                    "red" if hours < 24 else "amber",
                    unit,
                    f"{n} check{'s' if n != 1 else ''} still open",
                    f"{who}: {arrives_text(hours).lower()}. The villa is not ready to welcome yet.",
                    f.id,
                )
            )
        if not d.caretaker_staff_id and hours < 72:
            out.append(_need("amber", unit, "Pick the caretaker", f"{who}: {arrives_text(hours).lower()}.", f.id))
        if f.state == "ready" and hours < 24:
            out.append(
                _need("amber", unit, "Ready to welcome", f"{who}: {arrives_text(hours).lower()}. Tap Check in.", f.id)
            )
    meals = ops_stay_meals.unconfirmed_meals(f, today) if f.state in stays.BEFORE_WELCOME + ("staying",) else []
    if meals:
        out.append(
            _need(
                "amber",
                unit,
                "Cook has not confirmed " + ", ".join(m.meal for m in meals),
                f"{who}: today's meals. Send the plan to the cook or mark it confirmed.",
                f.id,
            )
        )
    if f.state == "staying":
        due = [
            j
            for j in db.query(OpsJob).filter_by(tenant_id=f.tenant_id, file_id=f.id, kind="cleaning", status="open")
            if j.due_at and stays._aware(j.due_at).date() <= today
        ]
        if due:
            out.append(
                _need(
                    "amber",
                    unit,
                    "Mid-stay cleaning due",
                    f"{who} is staying. Mark it done when the cleaner is finished.",
                    f.id,
                )
            )
    if f.state == "checked_out":
        items = trips.readiness_items(db, f, "inspection")
        red = [i.label for i in items if i.status == "red"]
        if red:
            out.append(_need("red", unit, "Inspection found a problem", f"{who}: " + ", ".join(red) + ".", f.id))
        elif any(i.status == "pending" for i in items):
            out.append(
                _need(
                    "amber",
                    unit,
                    "Finish the check-out inspection",
                    f"{who} has left. Compare with the arrival photos.",
                    f.id,
                )
            )
        else:
            out.append(_need("amber", unit, "Mark the inspection done", f"{who} has left. Every check is in.", f.id))
    a = money.account(db, f)
    if a["extras_waiting"]:
        n = a["extras_waiting"]
        out.append(
            _need(
                "amber",
                unit,
                f"{n} extra{'s' if n != 1 else ''} waiting for you",
                "Approve or remove before billing.",
                f.id,
            )
        )
    if f.state == "settling":
        dep = a["deposit"]
        out_h = (now - stays._aware(f.returned_at)).total_seconds() / 3600 if f.returned_at else 0
        if dep is not None and dep["status"] == "held":
            out.append(
                _need(
                    "red" if out_h > 48 else "amber",
                    unit,
                    f"Decide the deposit Rs {dep['amount']:,}",
                    f"{who} has left. Refund it, or keep part of it with the inspection photos.",
                    f.id,
                )
            )
        if a["outstanding"] > 0:
            out.append(
                _need("amber", unit, f"Collect Rs {a['outstanding']:,}", f"{who}'s balance after the stay.", f.id)
            )
        if (dep is None or dep["status"] != "held") and a["outstanding"] <= 0:
            out.append(_need("amber", unit, stays.stage(db, f)["next"] or "Close the stay", f"{who} has left.", f.id))
    return out


def build(db: Session, tenant_id: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    tenant = db.get(Tenant, tenant_id)
    tz = get_tz(tenant) if tenant else UTC
    today = booking_agenda_service.tenant_today(db, tenant_id)
    trips.sync_files(db, tenant_id, today)
    db.flush()
    props = [
        p
        for p in db.query(Property)
        .filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
        .order_by(Property.name)
        if not is_placeholder_name(p.name)
    ]
    names = {p.id: p.name for p in props}
    rows = (
        db.query(OpsFile, Stay)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsFile.tenant_id == tenant_id, OpsFile.pack == stays.PACK, OpsFile.state.in_(stays.LIVE))
        .order_by(Stay.check_in)
        .all()
    )
    needs: list[dict] = []
    file_needs: dict[str, list[dict]] = {}
    for f, stay in rows:
        fn = _file_needs(db, f, stay, names.get(stay.property_id, "Villa"), now, tz, today)
        file_needs[f.id] = fn
        needs += fn
    by_stay = {stay.id: f for f, stay in rows}
    for it in (
        db.query(OpsItem)
        .filter(OpsItem.tenant_id == tenant_id, OpsItem.status.in_(("open", "acknowledged")))
        .order_by(OpsItem.created_at.desc())
        .limit(50)
    ):
        if it.dispatched_step is None and it.dispatch_after and esc_aware(it.dispatch_after) > now + HELD_FOR_LATER:
            continue  # held for a later day (a service request due next week): shows from the day before
        f = by_stay.get(it.stay_id) if it.stay_id else None
        title = it.title.split(": ", 1)[-1]
        n = _need(
            "red" if it.severity in _RED_SEVERITY else "amber",
            names.get(it.property_id, "Ops"),
            title[:1].upper() + title[1:],
            it.summary or "",
            f.id if f else None,
            action="resolve_item",
            item_id=it.id,
            key=f"item:{it.id}",
        )
        needs.append(n)
        if f is not None:
            file_needs.setdefault(f.id, []).append(n)
    needs.sort(key=lambda n: _ORDER[n["level"]])

    def who(s: Stay) -> str:
        return (s.guest.name if s.guest is not None else None) or "Guest"

    units = []
    for p in props:
        mine = [(f, s) for f, s in rows if s.property_id == p.id]
        cur = (
            next(((f, s) for f, s in mine if f.state == "staying"), None)
            or next(((f, s) for f, s in mine if f.state in ("checked_out", "settling")), None)
            or next(((f, s) for f, s in mine if f.state in stays.BEFORE_WELCOME), None)
        )
        if cur is None:
            units.append(
                {
                    "property_id": p.id,
                    "name": p.name,
                    "tone": "idle",
                    "status": "Free",
                    "line": "No stay coming up",
                    "problem": None,
                    "file_id": None,
                    "ready_pct": None,
                }
            )
            continue
        f, s = cur
        fn = file_needs.get(f.id, [])
        g = trips.gate(trips.readiness_items(db, f))
        status, line = {
            "staying": ("Guests staying", f"{who(s)} · leaves {s.check_out.strftime('%a %d %b')}"),
            "checked_out": ("Checked out, inspect", f"{who(s)} · left"),
            "settling": ("Checked out, to settle", f"{who(s)} · left"),
        }.get(
            f.state,
            (
                "Getting ready",
                f"{who(s)} · arrives {s.check_in.strftime('%a %d %b')}"
                + (f" {s.check_in_time}" if s.check_in_time else ""),
            ),
        )
        units.append(
            {
                "property_id": p.id,
                "name": p.name,
                "tone": "red" if any(n["level"] == "red" for n in fn) else "amber" if fn else "ok",
                "status": status,
                "line": line,
                "problem": fn[0]["title"] if fn else None,
                "file_id": f.id,
                "ready_pct": round(100 * g["green"] / g["total"])
                if g["total"] and f.state in stays.BEFORE_WELCOME
                else None,
            }
        )

    day = []
    horizon = today + timedelta(days=1)
    for f, s in rows:
        unit = names.get(s.property_id, "Villa")
        tone = "red" if any(n["level"] == "red" for n in file_needs.get(f.id, [])) else "ok"
        if f.state == "staying":
            day.append(
                {
                    "date": today.isoformat(),
                    "time": None,
                    "now": True,
                    "what": f"{unit}: guests staying",
                    "sub": who(s),
                    "file_id": f.id,
                    "tone": tone,
                }
            )
            if s.check_out <= horizon:
                day.append(
                    {
                        "date": s.check_out.isoformat(),
                        "time": s.check_out_time,
                        "now": False,
                        "what": f"{unit}: check-out",
                        "sub": f"{who(s)} · inspection + photos",
                        "file_id": f.id,
                        "tone": "idle",
                    }
                )
        elif f.state in stays.BEFORE_WELCOME and today <= s.check_in <= horizon:
            g = trips.gate(trips.readiness_items(db, f))
            day.append(
                {
                    "date": s.check_in.isoformat(),
                    "time": s.check_in_time,
                    "now": False,
                    "what": f"{unit}: guests arrive",
                    "sub": f"{who(s)} · {g['green']} of {g['total']} checks green",
                    "file_id": f.id,
                    "tone": "ok" if g["ready"] else "amber",
                }
            )
    day.sort(key=lambda e: (not e["now"], e["date"], e["time"] or "99:99"))
    spec = packs.get(stays.PACK)
    return {
        "date": today.isoformat(),
        "pack": stays.PACK,
        "unit_word": spec["unit_word"],
        "file_word": spec["file_word"],
        "units": units,
        "needs": needs,
        "day": day,
        "counts": {
            "arriving": sum(1 for f, s in rows if f.state in stays.BEFORE_WELCOME and today <= s.check_in <= horizon),
            "staying": sum(1 for f, _ in rows if f.state == "staying"),
            "leaving": sum(1 for f, s in rows if f.state == "staying" and s.check_out <= horizon),
        },
    }
