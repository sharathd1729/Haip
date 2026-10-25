"""Caravan trips: the ops file's state machine, readiness gate and "next step" (port of the Ratha prototype's workflow.ts,
gate.ts and stage.ts).

handed_over -> (Accept: route + km allowance) -> crew assigned -> readiness -> dispatch_ready (every critical gate item green)
-> on_trip (Dispatch: always a person's tap, with the start odometer) -> returned (end odometer; extra distance billed on the
booking) -> closed (balance collected, deposit resolved, vehicle checked, report approved, no extra left undecided).
A booking cancelled before it leaves turns its file to cancelled.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.ops import StaffProfile
from app.models.ops_files import OpsChecklistTemplate, OpsFile, OpsJob, OpsJobItem
from app.models.property import Stay
from app.models.stay_finance import StayDeposit
from app.models.tenant import Tenant
from app.schemas.ops_files import AcceptIn, CaravanDetails, CrewIn
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import ops_rates

PACK = "caravan_rv"
LIVE_STAY = ("confirmed", "checked_in", "checked_out")
BEFORE_ROAD = ("handed_over", "crew_assigned", "readiness", "dispatch_ready")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


# ── Files ───────────────────────────────────────────────────────────────────

def template(db: Session, tenant_id: str, pack: str, kind: str) -> OpsChecklistTemplate:
    """The business's checklist for pack + kind, created from the pack's defaults the first time."""
    t = db.query(OpsChecklistTemplate).filter_by(tenant_id=tenant_id, pack=pack, kind=kind).first()
    if t is None:
        spec = packs.get(pack)["checklists"][kind]
        t = OpsChecklistTemplate(tenant_id=tenant_id, pack=pack, kind=kind, name=spec["name"], items=list(spec["items"]))
        db.add(t)
        db.flush()
    return t


def _open_job(db: Session, f: OpsFile, kind: str, property_id: Optional[str]) -> OpsJob:
    t = template(db, f.tenant_id, f.pack, kind)
    job = OpsJob(tenant_id=f.tenant_id, file_id=f.id, property_id=property_id, kind=kind, template_id=t.id, status="open")
    db.add(job)
    db.flush()
    for it in t.items:
        db.add(OpsJobItem(tenant_id=f.tenant_id, job_id=job.id, key=it["key"], label=it["label"], critical=bool(it["critical"]),
                          source=it.get("source", "staff"), photo_required=bool(it.get("photo")), status="pending"))
    db.flush()
    return job


def ensure_file(db: Session, tenant_id: str, stay: Stay, pack: Optional[str] = None) -> Optional[OpsFile]:
    """The booking's ops file, created when the booking is live and the business has a pack. Idempotent."""
    f = db.query(OpsFile).filter_by(tenant_id=tenant_id, stay_id=stay.id).first()
    if f is not None:
        return f
    if pack is None:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        pack = packs.pack_for_business_type(tenant.business_type if tenant else None)
    if pack != PACK or stay.status not in LIVE_STAY:
        return None
    r = ops_rates.for_stay(db, stay)
    d = CaravanDetails(allowance_km=r.allowance_km, extra_km_rate=r.extra_km_rate,
                             rate_includes_gst=r.rate_includes_gst, rate_source=r.source)
    f = OpsFile(tenant_id=tenant_id, stay_id=stay.id, pack=pack, state=packs.get(pack)["first_state"], details={})
    money.save_details(f, d)
    db.add(f)
    db.flush()
    _open_job(db, f, "readiness", stay.property_id)
    money.event(db, f, "Booking confirmed, trip file created", auto=True)
    return f


def sync_files(db: Session, tenant_id: str, today: date) -> dict:
    """Create files for live bookings not yet ended; mark files of cancelled bookings (only before the trip leaves)."""
    created = cancelled = 0
    have = {sid for (sid,) in db.query(OpsFile.stay_id).filter(OpsFile.tenant_id == tenant_id)}
    for stay in (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.status.in_(LIVE_STAY), Stay.check_out >= today)):
        if stay.id not in have and ensure_file(db, tenant_id, stay) is not None:
            created += 1
    for f, status in (db.query(OpsFile, Stay.status).join(Stay, Stay.id == OpsFile.stay_id)
                      .filter(OpsFile.tenant_id == tenant_id, OpsFile.state.in_(BEFORE_ROAD), Stay.status == "cancelled")):
        f.state = "cancelled"
        money.event(db, f, "Booking cancelled in HAIP", auto=True)
        cancelled += 1
    return {"created": created, "cancelled": cancelled}


def get_file(db: Session, tenant_id: str, file_id: str) -> OpsFile:
    f = db.query(OpsFile).filter_by(id=file_id, tenant_id=tenant_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="Ops file not found")
    return f


# ── Readiness gate ──────────────────────────────────────────────────────────

def readiness_items(db: Session, f: OpsFile) -> list[OpsJobItem]:
    job = db.query(OpsJob).filter_by(tenant_id=f.tenant_id, file_id=f.id, kind="readiness").order_by(OpsJob.created_at).first()
    if job is None:
        return []
    return db.query(OpsJobItem).filter_by(tenant_id=f.tenant_id, job_id=job.id).order_by(OpsJobItem.created_at, OpsJobItem.key).all()


def gate(items: list[OpsJobItem]) -> dict:
    blocking = [i for i in items if i.critical and i.status != "green"]
    return {"blocking": [i.key for i in blocking], "red": [i.key for i in items if i.status == "red"],
            "green": sum(1 for i in items if i.status == "green"), "total": len(items), "ready": not blocking and bool(items)}


def _set(i: OpsJobItem, status: str, note: Optional[str], user_id: Optional[str], staff_id: Optional[str] = None) -> None:
    i.status, i.set_at, i.set_by_user_id, i.set_by_staff_id = status, _now(), user_id, staff_id
    if note is not None:
        i.note = note


def refresh(db: Session, f: OpsFile) -> None:
    """System items from HAIP data, then readiness <-> dispatch_ready. Payment is green once nothing is owed and any
    deposit is held; it is never turned red automatically."""
    if f.state not in ("readiness", "dispatch_ready", "crew_assigned", "handed_over"):
        return
    items = readiness_items(db, f)
    pay = next((i for i in items if i.key == "payment" and i.source == "system"), None)
    if pay is not None and pay.status != "red":
        a = money.account(db, f)
        dep = a["deposit"]
        ok = a["outstanding"] <= 0 and (dep is None or dep["amount"] <= 0 or dep["status"] == "held")
        pay.status = "green" if ok else "pending"
    ready = gate(items)["ready"]
    if f.state == "readiness" and ready:
        f.state = "dispatch_ready"
        money.event(db, f, "Every critical check is green: ready to dispatch", auto=True)
    elif f.state == "dispatch_ready" and not ready:
        f.state = "readiness"
        money.event(db, f, "A critical check is no longer green: back to getting ready", auto=True)


def set_item(db: Session, f: OpsFile, key: str, status: str, note: Optional[str], *, user_id: Optional[str] = None,
             staff_id: Optional[str] = None) -> OpsJobItem:
    if f.state not in BEFORE_ROAD:
        raise _conflict("The checklist is locked once the trip has left.")
    item = next((i for i in readiness_items(db, f) if i.key == key), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    _set(item, status, note, user_id, staff_id)
    money.event(db, f, f'Check "{item.label}": {status}' + (f" ({note})" if note else ""), actor_id=user_id)
    refresh(db, f)
    return item


# ── Steps ───────────────────────────────────────────────────────────────────

def accept(db: Session, f: OpsFile, body: AcceptIn, actor_id: str) -> OpsFile:
    if f.state not in BEFORE_ROAD:
        raise _conflict("The trip has already left.")
    d = money.details(f)
    d.route, d.stops = body.route.strip(), body.stops
    if body.allowance_km is not None:
        d.allowance_km, d.rate_source = body.allowance_km, "manager"
    if body.extra_km_rate is not None:
        d.extra_km_rate, d.rate_source = body.extra_km_rate, "manager"
    if body.rate_includes_gst is not None:
        d.rate_includes_gst = body.rate_includes_gst
    if d.allowance_km is None:
        raise HTTPException(status_code=422, detail="Enter the km included. The booking's quote does not say.")
    money.save_details(f, d)
    f.accepted_at, f.accepted_by = _now(), actor_id
    route = next((i for i in readiness_items(db, f) if i.key == "route"), None)
    if route is not None:
        _set(route, "green", "Checked on Accept", actor_id)
    money.event(db, f, f"Accepted: {d.route}, {int(d.allowance_km):,} km included", actor_id=actor_id)
    refresh(db, f)
    return f


def _overlaps(a: Stay, b: Stay) -> bool:
    return a.check_in < b.check_out and b.check_in < a.check_out


def set_crew(db: Session, f: OpsFile, body: CrewIn, actor_id: str) -> OpsFile:
    if f.state not in BEFORE_ROAD:
        raise _conflict("The trip has already left.")
    if body.driver_staff_id == body.helper_staff_id:
        raise HTTPException(status_code=422, detail="Pick two different people for driver and helper.")
    crew = {s.id: s for s in db.query(StaffProfile).filter(StaffProfile.tenant_id == f.tenant_id,
                                                           StaffProfile.id.in_([body.driver_staff_id, body.helper_staff_id]))}
    for sid, role in ((body.driver_staff_id, "driver"), (body.helper_staff_id, "helper")):
        if sid not in crew or not crew[sid].active:
            raise HTTPException(status_code=422, detail=f"Pick an active {role} from your staff list.")
    stay = money.stay_of(db, f)
    others = (db.query(OpsFile, Stay).join(Stay, Stay.id == OpsFile.stay_id)
              .filter(OpsFile.tenant_id == f.tenant_id, OpsFile.id != f.id, OpsFile.state.notin_(("closed", "cancelled"))))
    for o, ostay in others:
        if not _overlaps(stay, ostay):
            continue
        od = money.details(o)
        for sid in (body.driver_staff_id, body.helper_staff_id):
            if sid in (od.driver_staff_id, od.helper_staff_id):
                raise _conflict(f"{crew[sid].name} is already on another trip on those dates.")
    d = money.details(f)
    d.driver_staff_id, d.helper_staff_id = body.driver_staff_id, body.helper_staff_id
    money.save_details(f, d)
    if f.state in ("handed_over", "crew_assigned"):
        f.state = "readiness"
    money.event(db, f, f"Crew: {crew[body.driver_staff_id].name} (driver), {crew[body.helper_staff_id].name} (helper)",
                actor_id=actor_id)
    refresh(db, f)
    return f


def _last_reading(db: Session, f: OpsFile, property_id: str) -> Optional[int]:
    best = None
    for o in (db.query(OpsFile).join(Stay, Stay.id == OpsFile.stay_id)
              .filter(OpsFile.tenant_id == f.tenant_id, OpsFile.id != f.id, Stay.property_id == property_id)):
        od = money.details(o)
        for v in (od.start_odometer, od.end_odometer):
            if v is not None and (best is None or v > best):
                best = v
    return best


def dispatch(db: Session, f: OpsFile, start_odometer: int, actor_id: str) -> OpsFile:
    """The one tap that is never automatic (RathaOS)."""
    refresh(db, f)
    if f.state != "dispatch_ready" or not gate(readiness_items(db, f))["ready"]:
        raise _conflict("Not ready to dispatch: some critical checks are not green yet.")
    stay = money.stay_of(db, f)
    last = _last_reading(db, f, stay.property_id)
    if last is not None and start_odometer < last:
        raise HTTPException(status_code=422, detail=f"Odometer {start_odometer:,} km is below the last reading {last:,} km.")
    d = money.details(f)
    d.start_odometer = start_odometer
    money.save_details(f, d)
    f.state, f.dispatched_at, f.dispatched_by = "on_trip", _now(), actor_id
    money.event(db, f, f"Dispatched. Start odometer {start_odometer:,} km", actor_id=actor_id)
    append_audit(db, tenant_id=f.tenant_id, action="ops.trip.dispatched", actor_user_id=actor_id, target_type="ops_file",
                 target_id=f.id, payload={"stay_id": f.stay_id, "start_odometer": start_odometer})
    return f


def end_trip(db: Session, f: OpsFile, end_odometer: int, *, actor_id: Optional[str] = None,
             staff_id: Optional[str] = None) -> OpsFile:
    d = money.details(f)
    if f.state != "on_trip" or d.start_odometer is None:
        raise _conflict("This trip is not on the road.")
    if end_odometer < d.start_odometer:
        raise HTTPException(status_code=422, detail=f"End odometer {end_odometer:,} km is below the start {d.start_odometer:,} km.")
    d.end_odometer = end_odometer
    money.save_details(f, d)
    f.state, f.returned_at = "returned", _now()
    charge = money.post_extra_km(db, f)
    dist, over = money.extra_km(money.details(f))
    money.event(db, f, f"Returned. End odometer {end_odometer:,} km ({dist:,} km"
                + (f", {over:,} km over: Rs {charge:,} added to the bill)" if over else ", within the allowance)"),
                auto=staff_id is not None, actor_id=actor_id)
    return f


def settle(db: Session, f: OpsFile, step: str, actor_id: str) -> OpsFile:
    if f.state != "returned":
        raise _conflict("The trip has not returned yet.")
    if step == "return_checked":
        f.return_checked_at, f.return_checked_by = _now(), actor_id
        money.event(db, f, "Vehicle checked on return", actor_id=actor_id)
    else:
        f.report_approved_at, f.report_approved_by = _now(), actor_id
        money.event(db, f, "Trip account report approved", actor_id=actor_id)
    return f


def close_blockers(db: Session, f: OpsFile) -> list[str]:
    a = money.account(db, f)
    dep = a["deposit"]
    return [m for m in (
        a["outstanding"] > 0 and f"balance Rs {a['outstanding']:,} not collected",
        dep is not None and dep["status"] == "held" and "deposit not refunded",
        f.report_approved_at is None and "report not approved",
        f.return_checked_at is None and "vehicle not checked on return",
        a["extras_waiting"] and "extras waiting for your decision (approve or remove them)",
    ) if m]


def close(db: Session, f: OpsFile, actor_id: str) -> OpsFile:
    if f.state != "returned":
        raise _conflict("The trip has not returned yet.")
    missing = close_blockers(db, f)
    if missing:
        raise _conflict("Cannot close yet: " + ", ".join(missing) + ".")
    f.state, f.closed_at, f.closed_by = "closed", _now(), actor_id
    money.event(db, f, "Trip closed", actor_id=actor_id)
    append_audit(db, tenant_id=f.tenant_id, action="ops.trip.closed", actor_user_id=actor_id, target_type="ops_file",
                 target_id=f.id, payload={"stay_id": f.stay_id})
    return f


# ── What the manager sees ───────────────────────────────────────────────────

def stage(db: Session, f: OpsFile) -> dict:
    """The step (1-6), its tasks and one line saying what to do next. Empty next = nothing left."""
    names = packs.get(f.pack)["step_names"]
    step = packs.step_of(f.pack, f.state)
    d, a = money.details(f), money.account(db, f)
    g = gate(readiness_items(db, f))
    t = lambda key, label, done, hint=None: {"key": key, "label": label, "done": bool(done), "hint": hint}  # noqa: E731
    route = t("route", "Route and km included set", f.accepted_at and d.allowance_km,
              f"{d.route}, {int(d.allowance_km or 0):,} km included" if d.allowance_km else "Needed to bill extra km")
    crew = t("crew", "Driver and helper assigned", d.driver_staff_id and d.helper_staff_id)
    waiting = a["extras_waiting"]
    if f.state == "handed_over":
        tasks = [route, crew]
    elif f.state in ("crew_assigned", "readiness"):
        tasks = [route, crew, t("pay", "Payment received", a["outstanding"] <= 0,
                                f"Rs {a['outstanding']:,} still to pay" if a["outstanding"] > 0 else "Fully paid"),
                 t("extras", "Extras decided", not waiting, f"{waiting} waiting" if waiting else None),
                 t("gate", "Vehicle checklist complete", g["ready"], f"{g['green']} of {g['total']} green")]
    elif f.state == "dispatch_ready":
        tasks = [t("start", "Enter the start odometer and dispatch", False, "Always your tap")]
    elif f.state == "on_trip":
        tasks = [t("extras", "Extras decided", not waiting, f"{waiting} waiting" if waiting else None),
                 t("end", "Vehicle back and end odometer entered", False)]
    elif f.state == "returned":
        dep = a["deposit"]
        tasks = [t("ret", "Vehicle checked on return", f.return_checked_at, "Compare with the handover photos"),
                 t("extras", "Extras decided", not waiting),
                 t("bal", "Balance collected", a["outstanding"] <= 0, f"Rs {a['outstanding']:,} due" if a["outstanding"] > 0 else None)]
        if dep is not None and dep["status"] in ("held", "released", "forfeited"):
            tasks.append(t("dep", "Deposit refunded", dep["status"] in ("released", "forfeited"),
                           f"Rs {dep['amount']:,}, due within 48 hours of return"))
        tasks.append(t("rep", "Trip account report approved", f.report_approved_at))
    else:
        tasks = []
    open_ = next((x for x in tasks if not x["done"]), None)
    nxt = ("" if f.state in ("closed", "cancelled") else open_["label"] if open_
           else "Close the trip" if f.state == "returned" else "Waiting on the checklist")
    return {"step": step + 1, "step_name": names[step], "step_names": list(names), "tasks": tasks, "next": nxt}
