"""Villa stays (ops pack "villa", phase 4): the stay file's state machine, people, meal plan, mid-stay cleaning, deposit
decision and "next step". The generic parts (files, events, checklist jobs, extras, expenses, money) are shared with the
caravan pack: ops_trip_service (template, _open_job, readiness_items, gate, _set) and ops_money.

preparing -> ready (every critical "Ready to welcome" item green) -> staying (Check-in: always a person's tap; keys handed
over, deposit collected or not; stays of 4+ nights get a cleaning job every 3rd day) -> checked_out (the check-out
inspection opens) -> settling (inspection done) -> closed (deposit decided, balance collected, report approved, no extra
undecided). A booking cancelled before check-in turns its file to cancelled (ops_trip_service.sync_files).
OpsFile columns shared with the caravan pack: dispatched_at = welcomed, returned_at = checked out, return_checked_at =
inspection done.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.tenant_tz import get_tz
from app.models.ops import StaffDuty, StaffProfile
from app.models.ops_files import OpsFile, OpsJob, OpsJobItem
from app.models.property import Stay
from app.models.stay_finance import StayDeposit, StayServiceRequest
from app.models.tenant import Tenant
from app.schemas.ops_files import CheckInIn, DepositDecisionIn, PeopleIn, VillaDetails
from app.services import booking_agenda_service, ops_stay_meals
from app.services import ops_money as money
from app.services import ops_pack_catalog as packs
from app.services import ops_trip_service as trips

PACK = "villa"  # the first stay pack; vacation_rental, homestay and boutique_hotel files run this machine too
BEFORE_WELCOME = ("preparing", "ready")
LIVE = BEFORE_WELCOME + ("staying", "checked_out", "settling")
CLEAN_EVERY_DAYS = 3  # the villa pack's midstay_clean; each stay pack sets its own (None = no tracked mid-stay clean)
CLEAN_MIN_NIGHTS = 4
# Who does what at a villa: the file's role -> the staff duty that suggests a person for it (schemas/ops.py DUTIES).
ROLES = {"caretaker": "caretaker", "cook": "fnb", "cleaner": "housekeeping"}


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=409, detail=msg)


def _d(f: OpsFile) -> VillaDetails:
    return money.details(f)  # type: ignore[return-value]


def _suggest(db: Session, tenant_id: str, property_id: str, duty: str) -> str | None:
    """The one active person holding this duty at the villa (or everywhere). Two or more = the manager picks."""
    ids = {
        sid
        for (sid,) in db.query(StaffDuty.staff_id)
        .join(StaffProfile, StaffProfile.id == StaffDuty.staff_id)
        .filter(
            StaffDuty.tenant_id == tenant_id,
            StaffDuty.duty == duty,
            StaffProfile.active.is_(True),
            (StaffDuty.property_id == property_id) | StaffDuty.property_id.is_(None),
        )
    }
    return ids.pop() if len(ids) == 1 else None


def _clean_rule(pack: str) -> tuple[int, int] | None:
    """(every N days, from M nights) for the pack's mid-stay clean, or None."""
    rule = packs.get(pack).get("midstay_clean")
    return (int(rule["every_days"]), int(rule["min_nights"])) if rule else None


def unit_words(pack: str) -> tuple[str, str]:
    """('Villa', 'Caretaker') / ('Room', 'Front desk'): the pack's unit and host words for screens and the timeline."""
    spec = packs.get(pack)
    return spec["unit_word"].capitalize(), spec.get("host_label", "Caretaker")


def create_file(db: Session, tenant_id: str, stay: Stay, pack: str = PACK) -> OpsFile:
    """The stay's file (called by ops_trip_service.ensure_file). A guest already in the unit starts at "staying"."""
    d = VillaDetails(
        **{f"{role}_staff_id": _suggest(db, tenant_id, stay.property_id, duty) for role, duty in ROLES.items()}
    )
    state = {"checked_in": "staying", "checked_out": "checked_out"}.get(stay.status, packs.get(pack)["first_state"])
    f = OpsFile(tenant_id=tenant_id, stay_id=stay.id, pack=pack, state=state, details={})
    money.save_details(f, d)
    db.add(f)
    db.flush()
    trips._open_job(db, f, "readiness", stay.property_id)
    if state == "checked_out":
        trips._open_job(db, f, "inspection", stay.property_id)
    money.event(db, f, "Booking confirmed, stay file created", auto=True)
    return f


# ── Checklists ──────────────────────────────────────────────────────────────


def job_kind(f: OpsFile) -> str | None:
    """Which checklist a photo or a tap fills now: Ready to welcome before check-in, the inspection after check-out."""
    return "readiness" if f.state in BEFORE_WELCOME else "inspection" if f.state == "checked_out" else None


def refresh(db: Session, f: OpsFile) -> None:
    """System items from HAIP data, then preparing <-> ready. Payment and guest details inform; they never block."""
    if f.state not in BEFORE_WELCOME:
        return
    items = trips.readiness_items(db, f)
    stay = money.stay_of(db, f)
    system = {
        "payment": money.account(db, f)["outstanding"] <= 0,
        "guests": bool(stay.guest is not None and stay.guest.name and (stay.adults or 0) >= 1),
    }
    for i in items:
        if i.source == "system" and i.key in system and i.status != "red":
            i.status = "green" if system[i.key] else "pending"
    ready = trips.gate(items)["ready"]
    if f.state == "preparing" and ready:
        f.state = "ready"
        money.event(db, f, "Every critical check is green: ready to welcome the guest", auto=True)
    elif f.state == "ready" and not ready:
        f.state = "preparing"
        money.event(db, f, "A critical check is no longer green: back to getting ready", auto=True)


def set_item(
    db: Session,
    f: OpsFile,
    key: str,
    status: str,
    note: str | None,
    *,
    user_id: str | None = None,
    staff_id: str | None = None,
) -> OpsJobItem:
    kind = job_kind(f)
    if kind is None:
        raise _conflict("No checklist is open: the guest is staying, or the stay is settled.")
    item = next((i for i in trips.readiness_items(db, f, kind) if i.key == key), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    trips._set(item, status, note, user_id, staff_id)
    money.event(db, f, f'Check "{item.label}": {status}' + (f" ({note})" if note else ""), actor_id=user_id)
    refresh(db, f)
    return item


# ── People ──────────────────────────────────────────────────────────────────


def set_people(db: Session, f: OpsFile, body: PeopleIn, actor_id: str) -> OpsFile:
    if f.state in ("closed", "cancelled"):
        raise _conflict("This stay is closed.")
    ids = [i for i in (body.caretaker_staff_id, body.cook_staff_id, body.cleaner_staff_id) if i]
    staff = {
        s.id: s
        for s in db.query(StaffProfile).filter(StaffProfile.tenant_id == f.tenant_id, StaffProfile.id.in_(ids or [""]))
    }
    for sid in ids:
        if sid not in staff or not staff[sid].active:
            raise HTTPException(status_code=422, detail="Pick active people from your staff list.")
    d = _d(f)
    d.caretaker_staff_id, d.cook_staff_id, d.cleaner_staff_id = (
        body.caretaker_staff_id,
        body.cook_staff_id,
        body.cleaner_staff_id,
    )
    money.save_details(f, d)
    words = ", ".join(
        f"{staff[i].name} ({role})"
        for role, i in zip(ROLES, (d.caretaker_staff_id, d.cook_staff_id, d.cleaner_staff_id), strict=True)
        if i
    )
    money.event(db, f, f"People: {words or 'nobody set'}", actor_id=actor_id)
    for j in _cleaning(db, f):
        if j.status == "open":
            j.staff_id = d.cleaner_staff_id
    return f


def names(db: Session, f: OpsFile) -> dict:
    d = _d(f)
    ids = {role: getattr(d, f"{role}_staff_id") for role in ROLES}
    found = {
        s.id: s.name
        for s in db.query(StaffProfile).filter(
            StaffProfile.tenant_id == f.tenant_id, StaffProfile.id.in_([i for i in ids.values() if i] or [""])
        )
    }
    return {role: found.get(i) for role, i in ids.items()}


# ── Welcome, stay, check-out ────────────────────────────────────────────────


def _cleaning(db: Session, f: OpsFile) -> list[OpsJob]:
    return (
        db.query(OpsJob).filter_by(tenant_id=f.tenant_id, file_id=f.id, kind="cleaning").order_by(OpsJob.due_at).all()
    )


def check_in(db: Session, f: OpsFile, body: CheckInIn, actor_id: str) -> OpsFile:
    """The guest is welcomed. Always a person's tap, only once the villa is ready."""
    refresh(db, f)
    if f.state != "ready" or not trips.gate(trips.readiness_items(db, f))["ready"]:
        raise _conflict("Not ready to welcome: some critical checks are not green yet.")
    stay = money.stay_of(db, f)
    dep = db.query(StayDeposit).filter_by(tenant_id=f.tenant_id, stay_id=stay.id).first()
    today = booking_agenda_service.tenant_today(db, f.tenant_id)
    if body.deposit_collected:
        if dep is None:
            if body.deposit_amount is None:
                raise HTTPException(status_code=422, detail="Enter the deposit amount you collected.")
            dep = StayDeposit(tenant_id=f.tenant_id, stay_id=stay.id, amount=body.deposit_amount)
            db.add(dep)
        if dep.status in (None, "pending", "held"):
            dep.status, dep.collected_on = "held", dep.collected_on or today
    d = _d(f)
    d.keys_handed, d.deposit_collected, d.check_in_note = body.keys_handed, body.deposit_collected, body.note
    money.save_details(f, d)
    f.state, f.dispatched_at, f.dispatched_by = "staying", _now(), actor_id
    tenant = db.get(Tenant, f.tenant_id)
    tz = get_tz(tenant) if tenant else UTC
    nights = (stay.check_out - stay.check_in).days
    rule = _clean_rule(f.pack)
    if rule is not None and nights >= rule[1]:
        for k in range(rule[0], nights, rule[0]):
            due = datetime.combine(stay.check_in + timedelta(days=k), time(11, 0), tzinfo=tz)
            db.add(
                OpsJob(
                    tenant_id=f.tenant_id,
                    file_id=f.id,
                    property_id=stay.property_id,
                    kind="cleaning",
                    staff_id=d.cleaner_staff_id,
                    due_at=due,
                    status="open",
                )
            )
        db.flush()
    money.event(
        db,
        f,
        "Guest welcomed. Keys "
        + ("handed over" if body.keys_handed else "NOT handed over")
        + (f", deposit Rs {dep.amount:,} collected" if body.deposit_collected and dep else ", no deposit collected")
        + (f" ({body.note})" if body.note else ""),
        actor_id=actor_id,
    )
    append_audit(
        db,
        tenant_id=f.tenant_id,
        action="ops.stay.checked_in",
        actor_user_id=actor_id,
        target_type="ops_file",
        target_id=f.id,
        payload={"stay_id": f.stay_id, "keys_handed": body.keys_handed, "deposit_collected": body.deposit_collected},
    )
    from app.services import ops_form_c

    ops_form_c.sync(db, f)  # the guests have arrived: Form C for anyone from abroad (due in 24 h)
    return f


def finish_cleaning(
    db: Session, f: OpsFile, job_id: str | None = None, *, actor_id: str | None = None, staff_id: str | None = None
) -> OpsJob | None:
    """Mark a mid-stay clean done: the named job, else the earliest open one already due (a cleaner's photo)."""
    jobs = [j for j in _cleaning(db, f) if j.status == "open"]
    if job_id is not None:
        job = next((j for j in jobs if j.id == job_id), None)
        if job is None:
            raise HTTPException(status_code=404, detail="Open cleaning job not found")
    else:
        job = next((j for j in jobs if j.due_at is not None and _aware(j.due_at) <= _now() + timedelta(hours=12)), None)
        if job is None:
            return None
    job.status, job.completed_at = "done", _now()
    money.event(db, f, "Mid-stay cleaning done", auto=staff_id is not None, actor_id=actor_id)
    return job


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite returns naive datetimes


def check_out(db: Session, f: OpsFile, actor_id: str | None) -> OpsFile:
    if f.state != "staying":
        raise _conflict("The guest is not staying.")
    stay = money.stay_of(db, f)
    f.state, f.returned_at = "checked_out", _now()
    for j in _cleaning(db, f):
        if j.status == "open":
            j.status = "cancelled"
    trips._open_job(db, f, "inspection", stay.property_id)
    money.event(db, f, "Guest checked out. Check-out inspection opened", actor_id=actor_id)
    return f


# ── Settle and close ────────────────────────────────────────────────────────


def settle(db: Session, f: OpsFile, step: str, actor_id: str) -> OpsFile:
    if step == "return_checked":
        if f.state != "checked_out":
            raise _conflict("The guest has not checked out yet.")
        left = [i.label for i in trips.readiness_items(db, f, "inspection") if i.status == "pending"]
        if left:
            raise _conflict("Finish the inspection first: " + ", ".join(left) + ".")
        f.state, f.return_checked_at, f.return_checked_by = "settling", _now(), actor_id
        money.event(db, f, "Check-out inspection done", actor_id=actor_id)
    else:
        if f.state != "settling":
            raise _conflict("Finish the check-out inspection first.")
        f.report_approved_at, f.report_approved_by = _now(), actor_id
        money.event(db, f, "Stay account report approved", actor_id=actor_id)
    return f


def decide_deposit(db: Session, f: OpsFile, body: DepositDecisionIn, actor_id: str) -> StayDeposit:
    """Refund in full, or keep part (or all) of it with a reason; the inspection's problem photos back a deduction."""
    if f.state != "settling":
        raise _conflict("Finish the check-out inspection before deciding the deposit.")
    dep = db.query(StayDeposit).filter_by(tenant_id=f.tenant_id, stay_id=f.stay_id).first()
    if dep is None or dep.status != "held":
        raise _conflict("No deposit is held for this stay.")
    amount = Decimal(0)
    if body.decision == "deduct":
        if body.amount is None or not (body.reason or "").strip():
            raise HTTPException(status_code=422, detail="Enter the amount kept and the reason.")
        if body.amount > Decimal(str(dep.amount)):
            raise HTTPException(status_code=422, detail="The deduction can't be more than the deposit.")
        amount = body.amount
    evidence = [i.key for i in trips.readiness_items(db, f, "inspection") if i.status == "red" and i.photo_key]
    dep.status = "forfeited" if amount and amount == Decimal(str(dep.amount)) else "released"
    dep.deducted = amount
    dep.resolved_on = booking_agenda_service.tenant_today(db, f.tenant_id)
    if body.reason:
        dep.notes = body.reason.strip()
    d = _d(f)
    d.deposit_decision, d.deposit_reason = body.decision, (body.reason or "").strip() or None
    d.deposit_evidence = evidence if body.decision == "deduct" else []
    money.save_details(f, d)
    money.event(
        db,
        f,
        f"Deposit refunded in full (Rs {dep.amount:,})"
        if not amount
        else f"Deposit: Rs {amount:,} kept of Rs {dep.amount:,} ({d.deposit_reason})",
        actor_id=actor_id,
    )
    append_audit(
        db,
        tenant_id=f.tenant_id,
        action="ops.stay.deposit_decided",
        actor_user_id=actor_id,
        target_type="ops_file",
        target_id=f.id,
        payload={
            "stay_id": f.stay_id,
            "decision": body.decision,
            "deposit": str(dep.amount),
            "kept": str(amount),
            "reason": d.deposit_reason,
            "evidence": d.deposit_evidence,
        },
    )
    return dep


def close_blockers(db: Session, f: OpsFile) -> list[str]:
    a = money.account(db, f)
    dep = a["deposit"]
    return [
        m
        for m in (
            f.return_checked_at is None and "check-out inspection not done",
            a["outstanding"] > 0 and f"balance Rs {a['outstanding']:,} not collected",
            dep is not None and dep["status"] == "held" and "deposit not decided",
            f.report_approved_at is None and "report not approved",
            a["extras_waiting"] and "extras waiting for your decision (approve or remove them)",
        )
        if m
    ]


def close(db: Session, f: OpsFile, actor_id: str) -> OpsFile:
    if f.state != "settling":
        raise _conflict("The stay is not ready to settle yet.")
    missing = close_blockers(db, f)
    if missing:
        raise _conflict("Cannot close yet: " + ", ".join(missing) + ".")
    f.state, f.closed_at, f.closed_by = "closed", _now(), actor_id
    money.event(db, f, "Stay closed", actor_id=actor_id)
    append_audit(
        db,
        tenant_id=f.tenant_id,
        action="ops.stay.closed",
        actor_user_id=actor_id,
        target_type="ops_file",
        target_id=f.id,
        payload={"stay_id": f.stay_id},
    )
    return f


# ── What the manager sees ───────────────────────────────────────────────────

NEXT_WORDS = {
    "people": "Pick the caretaker, cook and cleaner",
    "gate": "Finish the Ready to welcome checklist",
    "checkin": "Welcome the guest: hand over the keys, collect the deposit",
    "extras": "Decide the extras the guest asked for",
    "clean": "Mid-stay cleaning is due",
    "meals": "Get the cook to confirm today's meals",
    "checkout": "Check the guest out when they leave",
    "inspect": "Finish the check-out inspection",
    "ret": "Mark the inspection done",
    "bal": "Collect the balance",
    "deposit": "Decide the deposit: refund it or keep part of it",
    "rep": "Approve the stay account report",
}


def service_requests(db: Session, f: OpsFile) -> list[StayServiceRequest]:
    return (
        db.query(StayServiceRequest)
        .filter_by(tenant_id=f.tenant_id, stay_id=f.stay_id)
        .order_by(StayServiceRequest.created_at)
        .all()
    )


def stage(db: Session, f: OpsFile) -> dict:
    names_ = packs.get(f.pack)["step_names"]
    step = packs.step_of(f.pack, f.state)
    unit, host = unit_words(f.pack)
    d, a = _d(f), money.account(db, f)
    today = booking_agenda_service.tenant_today(db, f.tenant_id)

    def t(key, label, done, hint=None):
        return {"key": key, "label": label, "done": bool(done), "hint": hint}

    waiting = a["extras_waiting"]
    extras = t("extras", "Extras decided", not waiting, f"{waiting} waiting" if waiting else None)
    if f.state in BEFORE_WELCOME:
        g = trips.gate(trips.readiness_items(db, f))
        tasks = [
            t("people", f"{host} assigned", d.caretaker_staff_id, "The cook and cleaner are set the same way"),
            t("gate", f"{unit} ready to welcome", g["ready"], f"{g['green']} of {g['total']} green"),
        ]
        if f.state == "ready":
            tasks.append(t("checkin", "Guest welcomed", False, "Always your tap"))
    elif f.state == "staying":
        due = [j for j in _cleaning(db, f) if j.status == "open" and j.due_at and _aware(j.due_at).date() <= today]
        meals = ops_stay_meals.unconfirmed_meals(f, today)
        # Each pack shows the steps it has: a tracked mid-stay clean (villa) and a cook's meal plan (packs with fnb staff).
        tasks = [extras]
        if _clean_rule(f.pack) is not None or due:
            tasks.append(t("clean", "Mid-stay cleaning done", not due))
        if "fnb" in packs.get(f.pack)["duties"] or meals:
            tasks.append(
                t("meals", "Today's meals confirmed by the cook", not meals, ", ".join(m.meal for m in meals) or None)
            )
        tasks.append(t("checkout", "Guest checked out", False))
    elif f.state == "checked_out":
        left = [i for i in trips.readiness_items(db, f, "inspection") if i.status == "pending"]
        tasks = [
            t("inspect", "Inspection photos in", not left, f"{len(left)} still to check" if left else None),
            t("ret", "Inspection done", f.return_checked_at),
        ]
    elif f.state == "settling":
        dep = a["deposit"]
        tasks = [
            extras,
            t(
                "bal",
                "Balance collected",
                a["outstanding"] <= 0,
                f"Rs {a['outstanding']:,} due" if a["outstanding"] > 0 else None,
            ),
        ]
        if dep is not None and dep["status"] in ("held", "released", "forfeited"):
            tasks.append(t("deposit", "Deposit decided", dep["status"] != "held", f"Rs {dep['amount']:,} held"))
        tasks.append(t("rep", "Stay account report approved", f.report_approved_at))
    else:
        tasks = []
    open_ = next((x for x in tasks if not x["done"]), None)
    over = f.state in ("closed", "cancelled")
    nxt = (
        ""
        if over
        else NEXT_WORDS.get(open_["key"], open_["label"])
        if open_
        else "Close the stay"
        if f.state == "settling"
        else "Waiting on the checklist"
    )
    key = None if over else open_["key"] if open_ else "close" if f.state == "settling" else "wait"
    return {
        "step": step + 1,
        "step_name": names_[step],
        "step_names": list(names_),
        "tasks": tasks,
        "next": nxt,
        "next_key": key,
    }
