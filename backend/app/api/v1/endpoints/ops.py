"""Operations module API (docs/ops/OPS_MODULE_PLAN.md). Capabilities: ops.read, ops.write, ops.manage.

Staff           GET/POST /ops/staff · PATCH /ops/staff/{id}
Roster          GET/POST /ops/shifts · DELETE /ops/shifts/{id}
                GET/POST /ops/shift-overrides · DELETE /ops/shift-overrides/{id}
                GET /ops/on-duty?duty=&property_id=&at=
Chains          GET /ops/escalation-chains · PUT /ops/escalation-chains · DELETE /ops/escalation-chains/{id}
Settings        GET/PUT /ops/settings · POST /ops/templates/install (creates the template pack as drafts to submit to Meta)
Items           GET /ops/items · POST /ops/items · GET /ops/items/{id}
                POST /ops/items/{id}/acknowledge | /resolve | /cancel

Alerts are never sent inside a request: the service queues ops_alert_sends and this module hands their ids to Celery after commit.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.database import get_db
from app.models.ops import (
    EscalationChain,
    OpsAlertSend,
    OpsEscalationEvent,
    OpsItem,
    OpsSettings,
    ShiftOverride,
    ShiftPattern,
)
from app.models.property import Property, Stay
from app.models.user import User
from app.schemas.ops import (
    DEFAULT_CHAIN,
    EscalationChainPut,
    OpsAlertSendOut,
    OpsEventOut,
    OpsItemAction,
    OpsItemCreate,
    OpsItemOut,
    OpsSettingsPut,
    ShiftOverrideCreate,
    ShiftOverrideOut,
    ShiftPatternCreate,
    ShiftPatternOut,
    StaffCreate,
    StaffUpdate,
    _hhmm_to_minute,
)
from app.services import ops_escalation_service as esc
from app.services import roster_service, staff_service
from app.services.authz_service import require_capability
from app.workers.tasks.ops_escalation import queue_delivery

router = APIRouter(prefix="/ops", tags=["operations"])

_read = require_capability("ops.read", "ops.manage")
_write = require_capability("ops.write", "ops.manage")
_manage = require_capability("ops.manage")


def _check_property(db: Session, tenant_id: str, property_id: str | None) -> None:
    if property_id and db.query(Property.id).filter_by(id=property_id, tenant_id=tenant_id).first() is None:
        raise HTTPException(status_code=422, detail="property_id is not a property in this workspace")


def _check_staff(db: Session, tenant_id: str, staff_id: str | None) -> None:
    if staff_id:
        staff_service.get_staff(db, tenant_id, staff_id)


# ── Staff ──────────────────────────────────────────────────────────────────


@router.get("/staff")
def list_staff(
    include_inactive: bool = False,
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    return staff_service.list_staff(db, user.tenant_id, include_inactive)


@router.post("/staff", status_code=201)
def create_staff(body: StaffCreate, user: User = Depends(_manage), db: Session = Depends(get_db)):
    staff = staff_service.create_staff(db, user.tenant_id, body)
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.staff.created",
        actor_user_id=user.id,
        target_type="staff_profile",
        target_id=staff.id,
        payload={
            "duties": [d.model_dump() for d in body.duties],
            "whatsapp_opt_in": body.whatsapp_opt_in,
        },
    )
    db.commit()
    return staff_service.to_out(db, staff)


@router.patch("/staff/{staff_id}")
def update_staff(
    staff_id: str,
    body: StaffUpdate,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    staff = staff_service.update_staff(db, user.tenant_id, staff_id, body)
    changed = sorted(body.model_dump(exclude_unset=True).keys())
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.staff.updated",
        actor_user_id=user.id,
        target_type="staff_profile",
        target_id=staff.id,
        payload={"fields": changed},
    )
    db.commit()
    return staff_service.to_out(db, staff)


# ── Roster ─────────────────────────────────────────────────────────────────


@router.get("/shifts", response_model=list[ShiftPatternOut])
def list_shifts(
    property_id: str | None = None,
    staff_id: str | None = None,
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    q = db.query(ShiftPattern).filter(ShiftPattern.tenant_id == user.tenant_id, ShiftPattern.active.is_(True))
    if property_id:
        q = q.filter((ShiftPattern.property_id == property_id) | ShiftPattern.property_id.is_(None))
    if staff_id:
        q = q.filter(ShiftPattern.staff_id == staff_id)
    return q.order_by(ShiftPattern.weekday, ShiftPattern.start_minute).all()


@router.post("/shifts", response_model=list[ShiftPatternOut], status_code=201)
def create_shifts(
    body: ShiftPatternCreate,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    _check_staff(db, user.tenant_id, body.staff_id)
    _check_property(db, user.tenant_id, body.property_id)
    start, end = _hhmm_to_minute(body.start), _hhmm_to_minute(body.end)
    if start >= 1440:
        raise HTTPException(status_code=422, detail="start must be before 24:00")
    rows = [
        ShiftPattern(
            tenant_id=user.tenant_id,
            staff_id=body.staff_id,
            duty=body.duty,
            property_id=body.property_id,
            weekday=wd,
            start_minute=start,
            end_minute=end or 1440,
            active=True,
        )
        for wd in body.weekdays
    ]
    db.add_all(rows)
    db.flush()
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.roster.shift_added",
        actor_user_id=user.id,
        target_type="staff_profile",
        target_id=body.staff_id,
        payload=body.model_dump(),
    )
    db.commit()
    return rows


@router.delete("/shifts/{shift_id}", status_code=204)
def delete_shift(shift_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    row = db.query(ShiftPattern).filter_by(id=shift_id, tenant_id=user.tenant_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    row.active = False
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.roster.shift_removed",
        actor_user_id=user.id,
        target_type="shift_pattern",
        target_id=row.id,
        payload={"staff_id": row.staff_id, "weekday": row.weekday, "duty": row.duty},
    )
    db.commit()


@router.get("/shift-overrides", response_model=list[ShiftOverrideOut])
def list_overrides(
    since: datetime | None = None,
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    since = since or datetime.now(UTC)
    return (
        db.query(ShiftOverride)
        .filter(ShiftOverride.tenant_id == user.tenant_id, ShiftOverride.ends_at > since)
        .order_by(ShiftOverride.starts_at)
        .all()
    )


@router.post("/shift-overrides", response_model=ShiftOverrideOut, status_code=201)
def create_override(
    body: ShiftOverrideCreate,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    if body.kind == "swap" and not body.replacement_staff_id:
        raise HTTPException(status_code=422, detail="a swap needs replacement_staff_id")
    if body.kind == "extra" and not body.duty:
        raise HTTPException(status_code=422, detail="an extra shift needs a duty")
    _check_staff(db, user.tenant_id, body.staff_id)
    _check_staff(db, user.tenant_id, body.replacement_staff_id)
    _check_property(db, user.tenant_id, body.property_id)
    row = ShiftOverride(tenant_id=user.tenant_id, created_by=user.id, **body.model_dump())
    db.add(row)
    db.flush()
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.roster.override_added",
        actor_user_id=user.id,
        target_type="shift_override",
        target_id=row.id,
        payload=body.model_dump(mode="json"),
    )
    db.commit()
    return row


@router.delete("/shift-overrides/{override_id}", status_code=204)
def delete_override(override_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    row = db.query(ShiftOverride).filter_by(id=override_id, tenant_id=user.tenant_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Override not found")
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.roster.override_removed",
        actor_user_id=user.id,
        target_type="shift_override",
        target_id=row.id,
        payload={"staff_id": row.staff_id, "kind": row.kind},
    )
    db.delete(row)
    db.commit()


@router.get("/on-duty")
def on_duty(
    duty: str,
    property_id: str | None = None,
    at: datetime | None = None,
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    """Who is on shift now, and who step 1 of the escalation chain would alert (empty = a roster gap)."""
    _check_property(db, user.tenant_id, property_id)
    staff = roster_service.on_shift(db, user.tenant_id, duty, property_id, at)
    first, skipped = roster_service.first_step_with_recipients(db, user.tenant_id, duty, property_id, 0, at=at)
    return {
        "on_shift": [{"id": s.id, "name": s.name} for s in staff],
        "first_alert_step": first.step if first else None,
        "first_alert_recipients": [r.name for r in first.recipients] if first else [],
        "skipped_steps": skipped,
        "roster_gap": not staff,
    }


# ── Escalation chains ──────────────────────────────────────────────────────


@router.get("/escalation-chains")
def list_chains(user: User = Depends(_read), db: Session = Depends(get_db)):
    rows = db.query(EscalationChain).filter_by(tenant_id=user.tenant_id).all()
    return {
        "default": DEFAULT_CHAIN,
        "chains": [{"id": r.id, "duty": r.duty, "property_id": r.property_id, "steps": r.steps} for r in rows],
    }


@router.put("/escalation-chains")
def put_chain(
    body: EscalationChainPut,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    _check_property(db, user.tenant_id, body.property_id)
    for step in body.steps:
        if step.type == "staff":
            _check_staff(db, user.tenant_id, step.staff_id)
        if step.type == "role" and not step.role:
            raise HTTPException(status_code=422, detail="a role step needs a role")
    steps = [s.model_dump(exclude_none=True) for s in body.steps]
    q = db.query(EscalationChain).filter_by(tenant_id=user.tenant_id, duty=body.duty)
    row = (
        q.filter(EscalationChain.property_id == body.property_id).first()
        if body.property_id
        else q.filter(EscalationChain.property_id.is_(None)).first()
    )
    if row is None:
        row = EscalationChain(
            tenant_id=user.tenant_id,
            duty=body.duty,
            property_id=body.property_id,
            steps=steps,
        )
        db.add(row)
    else:
        row.steps = steps
    db.flush()
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.chain.updated",
        actor_user_id=user.id,
        target_type="escalation_chain",
        target_id=row.id,
        payload=body.model_dump(),
    )
    db.commit()
    return {
        "id": row.id,
        "duty": row.duty,
        "property_id": row.property_id,
        "steps": row.steps,
    }


@router.delete("/escalation-chains/{chain_id}", status_code=204)
def delete_chain(chain_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    row = db.query(EscalationChain).filter_by(id=chain_id, tenant_id=user.tenant_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Chain not found")
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.chain.removed",
        actor_user_id=user.id,
        target_type="escalation_chain",
        target_id=row.id,
        payload={"duty": row.duty, "steps": row.steps},
    )
    db.delete(row)
    db.commit()


# ── Settings & templates ───────────────────────────────────────────────────


def _settings_out(db: Session, tenant_id: str) -> dict:
    from app.api.v1.endpoints.messaging import WATemplate
    from app.services.ops_templates import PACK

    cfg = esc.effective_settings(db, tenant_id)
    names = set(cfg["templates"].values()) | set(PACK)
    rows = {
        t.name: t
        for t in db.query(WATemplate).filter(WATemplate.tenant_id == tenant_id, WATemplate.name.in_(names)).all()
    }
    return {
        **cfg,
        "sla": {k: list(v) for k, v in cfg["sla"].items()},
        "template_status": {
            n: (rows[n].status.value if hasattr(rows[n].status, "value") else rows[n].status)
            if n in rows
            else "missing"
            for n in sorted(names)
        },
    }


@router.get("/settings")
def get_settings(user: User = Depends(_read), db: Session = Depends(get_db)):
    return _settings_out(db, user.tenant_id)


@router.put("/settings")
def put_settings(body: OpsSettingsPut, user: User = Depends(_manage), db: Session = Depends(get_db)):
    row = esc.get_settings_row(db, user.tenant_id)
    if row is None:
        row = OpsSettings(tenant_id=user.tenant_id)
        db.add(row)
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            setattr(row, field, value)
    db.flush()
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.settings.updated",
        actor_user_id=user.id,
        target_type="ops_settings",
        target_id=row.id,
        payload=data,
    )
    db.commit()
    return _settings_out(db, user.tenant_id)


@router.post("/templates/install")
def install_templates(user: User = Depends(_manage), db: Session = Depends(get_db)):
    """Create the ops template pack as local drafts (skips names that already exist). Submit them to Meta from the template editor."""
    from app.api.v1.endpoints.messaging import (
        TemplateCategory,
        TemplateStatus,
        WATemplate,
    )
    from app.services.ops_templates import PACK

    language = esc.effective_settings(db, user.tenant_id)["template_language"]
    created = []
    for name, spec in PACK.items():
        if db.query(WATemplate.id).filter_by(tenant_id=user.tenant_id, name=name).first():
            continue
        db.add(
            WATemplate(
                tenant_id=user.tenant_id,
                name=name,
                language=language,
                category=TemplateCategory(spec["category"]),
                status=TemplateStatus.DRAFT,
                components=spec["components"],
            )
        )
        created.append(name)
    if created:
        append_audit(
            db,
            tenant_id=user.tenant_id,
            action="ops.templates.installed",
            actor_user_id=user.id,
            target_type="wa_template",
            payload={"created": created},
        )
    db.commit()
    return {"created": created, **_settings_out(db, user.tenant_id)}


# ── Items ──────────────────────────────────────────────────────────────────


def _item(db: Session, tenant_id: str, item_id: str) -> OpsItem:
    item = db.query(OpsItem).filter_by(id=item_id, tenant_id=tenant_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/items", response_model=list[OpsItemOut])
def list_items(
    status: str | None = Query(default="live"),
    property_id: str | None = None,
    limit: int = Query(default=100, le=500),
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    q = db.query(OpsItem).filter(OpsItem.tenant_id == user.tenant_id)
    if status == "live":
        q = q.filter(OpsItem.status.in_(("open", "acknowledged")))
    elif status and status != "all":
        q = q.filter(OpsItem.status == status)
    if property_id:
        q = q.filter(OpsItem.property_id == property_id)
    return q.order_by(OpsItem.created_at.desc()).limit(limit).all()


@router.post("/items", response_model=OpsItemOut, status_code=201)
def create_item(body: OpsItemCreate, user: User = Depends(_write), db: Session = Depends(get_db)):
    _check_property(db, user.tenant_id, body.property_id)
    guest_id = None
    property_id = body.property_id
    if body.stay_id:
        stay = db.query(Stay).filter_by(id=body.stay_id, tenant_id=user.tenant_id).first()
        if stay is None:
            raise HTTPException(status_code=422, detail="stay_id is not a booking in this workspace")
        guest_id = stay.guest_id
        property_id = property_id or stay.property_id
    item, send_ids = esc.create_item(
        db,
        user.tenant_id,
        title=body.title,
        summary=body.summary,
        kind=body.kind,
        category=body.category,
        severity=body.severity,
        duty=body.duty,
        property_id=property_id,
        stay_id=body.stay_id,
        guest_id=guest_id,
        source="manager" if user.role.value in ("owner", "manager") else "staff",
        created_by=user.id,
    )
    db.commit()
    queue_delivery(user.tenant_id, send_ids)
    return item


@router.get("/items/{item_id}")
def get_item(item_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    item = _item(db, user.tenant_id, item_id)
    events = (
        db.query(OpsEscalationEvent)
        .filter_by(tenant_id=user.tenant_id, item_id=item.id)
        .order_by(OpsEscalationEvent.created_at)
        .all()
    )
    sends = (
        db.query(OpsAlertSend)
        .filter_by(tenant_id=user.tenant_id, item_id=item.id)
        .order_by(OpsAlertSend.created_at)
        .all()
    )
    return {
        "item": OpsItemOut.model_validate(item).model_dump(mode="json"),
        "events": [OpsEventOut.model_validate(e).model_dump(mode="json") for e in events],
        "alerts": [OpsAlertSendOut.model_validate(s).model_dump(mode="json") for s in sends],
    }


@router.post("/items/{item_id}/acknowledge", response_model=OpsItemOut)
def acknowledge_item(item_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    item = _item(db, user.tenant_id, item_id)
    if not esc.acknowledge(db, item, user_id=user.id, via="app"):
        raise HTTPException(status_code=409, detail=f"Item is already {item.status}")
    db.commit()
    return item


@router.post("/items/{item_id}/resolve", response_model=OpsItemOut)
def resolve_item(
    item_id: str,
    body: OpsItemAction,
    user: User = Depends(_write),
    db: Session = Depends(get_db),
):
    item = _item(db, user.tenant_id, item_id)
    if not esc.resolve(db, item, user_id=user.id, note=body.note):
        raise HTTPException(status_code=409, detail=f"Item is already {item.status}")
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.item.resolved",
        actor_user_id=user.id,
        target_type="ops_item",
        target_id=item.id,
        payload={"note": body.note},
    )
    db.commit()
    return item


@router.post("/items/{item_id}/cancel", response_model=OpsItemOut)
def cancel_item(
    item_id: str,
    body: OpsItemAction,
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    item = _item(db, user.tenant_id, item_id)
    if not esc.cancel(db, item, user_id=user.id, note=body.note):
        raise HTTPException(status_code=409, detail=f"Item is already {item.status}")
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.item.cancelled",
        actor_user_id=user.id,
        target_type="ops_item",
        target_id=item.id,
        payload={"note": body.note},
    )
    db.commit()
    return item
