"""Ops phase 2: the fleet's fitness (port of the Ratha prototype's derive.ts vehicle/people alerts and workflow.ts licence rule).

Papers     a vehicle's insurance / permit / FC / PUC / AIS-140 and a driver's HMV licence, with an expiry date. <= 30 days
           to go = amber, <= 7 days or expired = red. A critical vehicle paper that has expired, or expires before the trip
           ends, blocks Dispatch; a driver whose licence expires before the trip ends cannot be put on it.
Defects    reported by a person, or opened when a staff photo flags a critical checklist item. An open critical defect
           blocks Dispatch and keeps the vehicle off sale with a blocked_dates row (today .. today+7, kept rolling by the
           hourly job) that booking_service.find_conflicts already respects; closing it (ops.manage, audited) lifts it.
Services   due by date and/or km; vehicle km = the highest odometer reading on its ops files. Within 1,000 km or 14 days =
           amber, past due = red.
Inventory  onboard items with a par level; below par = amber "Restock ...".
What the screens read (the Fleet cards and the Today needs) is in ops_fleet_view.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.ops import StaffProfile
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsDefect, OpsInventoryItem, OpsPaper, OpsService
from app.models.property import BlockedDate, Property, Stay
from app.schemas.ops_fleet import (
    PAPER_KINDS,
    STAFF_PAPER_KINDS,
    VEHICLE_PAPER_KINDS,
    DefectIn,
    InventoryCountIn,
    InventoryIn,
    PaperIn,
    ServiceDoneIn,
    ServiceIn,
)
from app.services import ops_money as money
from app.services.vehicle_pool import is_placeholder_name

AMBER_DAYS, RED_DAYS = 30, 7
SERVICE_AMBER_KM, SERVICE_AMBER_DAYS = 1000, 14
BLOCK_DAYS = 7


def _now() -> datetime:
    return datetime.now(UTC)


def _day(d: date) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


def vehicles(db: Session, tenant_id: str) -> list[Property]:
    return [
        p
        for p in db.query(Property)
        .filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
        .order_by(Property.name)
        if not is_placeholder_name(p.name)
    ]


def _vehicle(db: Session, tenant_id: str, property_id: str) -> Property:
    p = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return p


def _get(db: Session, model, tenant_id: str, row_id: str, what: str):
    row = db.query(model).filter_by(id=row_id, tenant_id=tenant_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row


# ── Papers ──────────────────────────────────────────────────────────────────


def paper_level(expires_on: date | None, today: date) -> str | None:
    if expires_on is None:
        return None
    left = (expires_on - today).days
    return "red" if left <= RED_DAYS else "amber" if left <= AMBER_DAYS else None


def paper_words(p: OpsPaper, today: date) -> str:
    if p.expires_on is None:
        return "No expiry date entered"
    left = (p.expires_on - today).days
    if left < 0:
        return f"Expired on {_day(p.expires_on)}"
    if left == 0:
        return "Expires today"
    return f"Expires in {left} day{'s' if left != 1 else ''} ({_day(p.expires_on)})"


def add_paper(db: Session, tenant_id: str, body: PaperIn, actor_id: str | None = None) -> OpsPaper:
    """A new paper; it replaces the owner's current paper of the same kind (kept as history, inactive)."""
    if bool(body.property_id) == bool(body.staff_id):
        raise HTTPException(status_code=422, detail="A paper belongs to one vehicle or one person.")
    if body.property_id:
        _vehicle(db, tenant_id, body.property_id)
        if body.kind not in VEHICLE_PAPER_KINDS:
            raise HTTPException(status_code=422, detail="That paper is for a person, not a vehicle.")
    else:
        _get(db, StaffProfile, tenant_id, body.staff_id, "Staff member")
        if body.kind not in STAFF_PAPER_KINDS:
            raise HTTPException(status_code=422, detail="That paper is for a vehicle, not a person.")
    if body.kind != "other":
        db.query(OpsPaper).filter_by(
            tenant_id=tenant_id, property_id=body.property_id, staff_id=body.staff_id, kind=body.kind, active=True
        ).update({OpsPaper.active: False}, synchronize_session=False)
    p = OpsPaper(
        tenant_id=tenant_id,
        property_id=body.property_id,
        staff_id=body.staff_id,
        kind=body.kind,
        name=(body.name or "").strip() or PAPER_KINDS[body.kind][0],
        number=(body.number or "").strip() or None,
        expires_on=body.expires_on,
        active=True,
        created_by=actor_id,
    )
    db.add(p)
    db.flush()
    return p


def remove_paper(db: Session, tenant_id: str, paper_id: str) -> None:
    _get(db, OpsPaper, tenant_id, paper_id, "Paper").active = False
    db.flush()


_FILE_KINDS = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG",)),
    "image/webp": ("webp", (b"RIFF",)),
    "application/pdf": ("pdf", (b"%PDF",)),
}
MAX_PAPER_FILE = 5 * 1024 * 1024


def check_file(raw: bytes, content_type: str) -> str:
    """The stored extension, or a 422 naming the problem (type, size, a file that is not what it says)."""
    kind = _FILE_KINDS.get((content_type or "").split(";")[0].strip().lower())
    if kind is None:
        raise HTTPException(status_code=422, detail="The file must be a JPG, PNG, WebP or PDF.")
    if len(raw) > MAX_PAPER_FILE:
        raise HTTPException(status_code=422, detail="The file is larger than 5 MB.")
    if not any(raw.startswith(m) for m in kind[1]):
        raise HTTPException(status_code=422, detail=f"The file does not look like a real {kind[0].upper()}.")
    return kind[0]


def attach_file(db: Session, tenant_id: str, paper_id: str, raw: bytes, content_type: str) -> OpsPaper:
    from app.services import media_storage

    p = _get(db, OpsPaper, tenant_id, paper_id, "Paper")
    ext = check_file(raw, content_type)
    p.file_key = media_storage.upload_ops_paper(tenant_id, p.id, raw, content_type, ext)
    db.flush()
    return p


def licence(db: Session, tenant_id: str, staff_id: str) -> OpsPaper | None:
    return (
        db.query(OpsPaper)
        .filter_by(tenant_id=tenant_id, staff_id=staff_id, kind="hmv_licence", active=True)
        .order_by(OpsPaper.created_at.desc())
        .first()
    )


def licences(db: Session, tenant_id: str, staff_ids: list[str]) -> dict[str, OpsPaper]:
    if not staff_ids:
        return {}
    rows = db.query(OpsPaper).filter(
        OpsPaper.tenant_id == tenant_id,
        OpsPaper.staff_id.in_(staff_ids),
        OpsPaper.kind == "hmv_licence",
        OpsPaper.active.is_(True),
    )
    return {p.staff_id: p for p in rows}


def set_licence(db: Session, tenant_id: str, staff_id: str, number: str | None, expires_on: date | None, actor_id=None):
    """The staff screen's licence fields: edit the current licence paper in place, or start one."""
    cur = licence(db, tenant_id, staff_id)
    if cur is None:
        if number or expires_on:
            add_paper(
                db,
                tenant_id,
                PaperIn(staff_id=staff_id, kind="hmv_licence", number=number, expires_on=expires_on),
                actor_id,
            )
        return
    cur.number, cur.expires_on = (number or "").strip() or None, expires_on
    db.flush()


# ── Rules (ported from the prototype) ───────────────────────────────────────


def licence_problem(db: Session, staff: StaffProfile, trip_end: date) -> str | None:
    p = licence(db, staff.tenant_id, staff.id)
    if p is not None and p.expires_on is not None and p.expires_on < trip_end:
        return f"{staff.name}'s driving licence expires {_day(p.expires_on)}, before the trip ends."
    return None


def open_defects(db: Session, tenant_id: str, property_id: str | None = None) -> list[OpsDefect]:
    q = db.query(OpsDefect).filter(OpsDefect.tenant_id == tenant_id, OpsDefect.status == "open")
    if property_id:
        q = q.filter(OpsDefect.property_id == property_id)
    return q.order_by(OpsDefect.created_at).all()


def dispatch_problems(db: Session, f: OpsFile) -> list[str]:
    """Why this vehicle may not leave on this trip, in plain words. Empty = nothing from the fleet stops it."""
    from app.services.booking_agenda_service import tenant_today

    stay = money.stay_of(db, f)
    today = tenant_today(db, f.tenant_id)
    out = []
    for p in db.query(OpsPaper).filter_by(tenant_id=f.tenant_id, property_id=stay.property_id, active=True):
        if not PAPER_KINDS[p.kind][1] or p.expires_on is None or p.expires_on >= stay.check_out:
            continue
        out.append(
            f"{p.name} expired on {_day(p.expires_on)}"
            if p.expires_on < today
            else f"{p.name} expires {_day(p.expires_on)}, before the trip ends"
        )
    out += [
        f"Open defect: {d.title}" for d in open_defects(db, f.tenant_id, stay.property_id) if d.severity == "critical"
    ]
    driver_id = money.details(f).driver_staff_id
    driver = db.query(StaffProfile).filter_by(id=driver_id, tenant_id=f.tenant_id).first() if driver_id else None
    if driver is not None and (problem := licence_problem(db, driver, stay.check_out)):
        out.append(problem)
    return out


# ── Defects ─────────────────────────────────────────────────────────────────


def _block(db: Session, d: OpsDefect, today: date) -> None:
    b = BlockedDate(
        tenant_id=d.tenant_id,
        property_id=d.property_id,
        blocked_from=today.isoformat(),
        blocked_to=(today + timedelta(days=BLOCK_DAYS)).isoformat(),
        reason="maintenance",
        notes=f"Defect: {d.title}"[:500],
        is_active=True,
    )
    db.add(b)
    db.flush()
    d.block_id = b.id


def add_defect(
    db: Session,
    tenant_id: str,
    body: DefectIn,
    *,
    actor_id: str | None = None,
    source: str = "person",
    file_id: str | None = None,
    item_key: str | None = None,
    today: date | None = None,
) -> OpsDefect:
    _vehicle(db, tenant_id, body.property_id)
    d = OpsDefect(
        tenant_id=tenant_id,
        property_id=body.property_id,
        title=body.title.strip(),
        detail=body.detail,
        severity=body.severity,
        status="open",
        source=source,
        file_id=file_id,
        item_key=item_key,
        reported_by=actor_id,
    )
    db.add(d)
    db.flush()
    if d.severity == "critical":
        _block(db, d, today or datetime.now(UTC).date())
    return d


def defect_from_photo(db: Session, f: OpsFile, item_key: str, title: str, detail: str) -> OpsDefect | None:
    """A staff photo flagged a critical checklist item: one open defect per (trip, item), never a second."""
    open_ = db.query(OpsDefect).filter_by(tenant_id=f.tenant_id, file_id=f.id, item_key=item_key, status="open").first()
    if open_ is not None:
        return None
    stay = money.stay_of(db, f)
    return add_defect(
        db,
        f.tenant_id,
        DefectIn(property_id=stay.property_id, title=title[:200], detail=detail[:2000], severity="critical"),
        source="photo",
        file_id=f.id,
        item_key=item_key,
    )


def close_defect(db: Session, tenant_id: str, defect_id: str, note: str | None, actor_id: str) -> OpsDefect:
    d = _get(db, OpsDefect, tenant_id, defect_id, "Defect")
    if d.status != "open":
        raise HTTPException(status_code=409, detail="This defect is already closed.")
    d.status, d.closed_at, d.closed_by, d.close_note = "closed", _now(), actor_id, note
    if d.block_id:
        b = db.query(BlockedDate).filter_by(id=d.block_id, tenant_id=tenant_id).first()
        if b is not None:
            b.is_active = False
    append_audit(
        db,
        tenant_id=tenant_id,
        action="ops.defect.closed",
        actor_user_id=actor_id,
        target_type="ops_defect",
        target_id=d.id,
        payload={"property_id": d.property_id, "severity": d.severity, "title": d.title, "note": note},
    )
    db.flush()
    return d


def keep_blocks(db: Session, tenant_id: str, today: date) -> int:
    """Hourly: an open critical defect's block always reaches BLOCK_DAYS ahead, so the vehicle stays off sale."""
    n = 0
    want = (today + timedelta(days=BLOCK_DAYS)).isoformat()
    for d in open_defects(db, tenant_id):
        if d.severity != "critical":
            continue
        b = db.query(BlockedDate).filter_by(id=d.block_id, tenant_id=tenant_id).first() if d.block_id else None
        if b is None:
            _block(db, d, today)
            n += 1
        elif b.is_active and b.blocked_to < want:
            b.blocked_to = want
            n += 1
    return n


# ── Services and km ─────────────────────────────────────────────────────────


def vehicle_km(db: Session, tenant_id: str, property_id: str) -> int | None:
    best = None
    for f in (
        db.query(OpsFile)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(OpsFile.tenant_id == tenant_id, Stay.property_id == property_id)
    ):
        d = money.details(f)
        for v in (d.start_odometer, d.end_odometer):
            if v is not None and (best is None or v > best):
                best = v
    return best


def service_state(s: OpsService, km: int | None, today: date) -> tuple[str | None, str]:
    if s.status == "done":
        return (
            None,
            f"Done{f' on {_day(s.done_on)}' if s.done_on else ''}{f' at {s.done_km:,} km' if s.done_km else ''}",
        )
    if (s.due_km and km is not None and km >= s.due_km) or (s.due_on and today > s.due_on):
        return "red", "Overdue" + (f" (due at {s.due_km:,} km)" if s.due_km else f" (due {_day(s.due_on)})")
    parts = []
    if s.due_km and km is not None and s.due_km - km <= SERVICE_AMBER_KM:
        parts.append(f"due in {s.due_km - km:,} km")
    if s.due_on and (s.due_on - today).days <= SERVICE_AMBER_DAYS:
        left = (s.due_on - today).days
        parts.append("due today" if left == 0 else f"due in {left} day{'s' if left != 1 else ''}")
    if parts:
        return "amber", " or ".join(parts).capitalize()
    due = [f"at {s.due_km:,} km" if s.due_km else None, _day(s.due_on) if s.due_on else None]
    return None, "Due " + " or ".join(x for x in due if x) if any(due) else "No due date"


def add_service(db: Session, tenant_id: str, body: ServiceIn, actor_id: str | None) -> OpsService:
    _vehicle(db, tenant_id, body.property_id)
    if body.due_on is None and body.due_km is None:
        raise HTTPException(status_code=422, detail="Enter when it is due: a date, a km reading, or both.")
    s = OpsService(
        tenant_id=tenant_id,
        property_id=body.property_id,
        name=body.name.strip(),
        due_on=body.due_on,
        due_km=body.due_km,
        note=body.note,
        status="open",
        created_by=actor_id,
    )
    db.add(s)
    db.flush()
    return s


def service_done(db: Session, tenant_id: str, service_id: str, body: ServiceDoneIn, actor_id: str, today: date):
    s = _get(db, OpsService, tenant_id, service_id, "Service")
    if s.status == "done":
        raise HTTPException(status_code=409, detail="This service is already marked done.")
    s.status, s.done_on, s.done_by = "done", today, actor_id
    s.done_km = body.done_km or vehicle_km(db, tenant_id, s.property_id)
    if body.note:
        s.note = body.note
    db.flush()
    return s


def remove_service(db: Session, tenant_id: str, service_id: str) -> None:
    db.delete(_get(db, OpsService, tenant_id, service_id, "Service"))
    db.flush()


# ── Inventory ───────────────────────────────────────────────────────────────


def add_item(db: Session, tenant_id: str, body: InventoryIn, actor_id: str | None) -> OpsInventoryItem:
    _vehicle(db, tenant_id, body.property_id)
    name = body.name.strip()
    if db.query(OpsInventoryItem.id).filter_by(tenant_id=tenant_id, property_id=body.property_id, name=name).first():
        raise HTTPException(status_code=409, detail=f"{name} is already on this vehicle's list.")
    it = OpsInventoryItem(tenant_id=tenant_id, property_id=body.property_id, name=name, par=body.par, count=body.count)
    if body.count is not None:
        it.counted_at, it.counted_by = _now(), actor_id
    db.add(it)
    db.flush()
    return it


def set_count(db: Session, tenant_id: str, item_id: str, body: InventoryCountIn, actor_id: str) -> OpsInventoryItem:
    it = _get(db, OpsInventoryItem, tenant_id, item_id, "Item")
    if body.par is not None:
        it.par = body.par
    if body.count is not None:
        it.count, it.counted_at, it.counted_by = body.count, _now(), actor_id
    db.flush()
    return it


def remove_item(db: Session, tenant_id: str, item_id: str) -> None:
    db.delete(_get(db, OpsInventoryItem, tenant_id, item_id, "Item"))
    db.flush()


def low(it: OpsInventoryItem) -> bool:
    return it.count is not None and it.count < it.par
