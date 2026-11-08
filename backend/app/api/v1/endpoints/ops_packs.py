"""The business's ops pack (Ops 2, gap 7: packs as data) and self check-in.

GET    /ops/pack                                  flow, words, steps, pack data, checklists       ops.read
PUT    /ops/pack/config                           duties, issue types, paperwork, add-ons, timings ops.manage
GET    /ops/pack/checklists/{kind}?property_id=   the checklist a job there uses                   ops.read
PUT    /ops/pack/checklists/{kind}?property_id=   edit the default, or that property's own copy    ops.manage
DELETE /ops/pack/checklists/{kind}?property_id=   the property goes back to the default            ops.manage
GET    /ops/properties/{id}/self-check-in         values only for ops.manage, else what is set     ops.read
PUT    /ops/properties/{id}/self-check-in         switch + steps / lock code / key box            ops.manage

Every write is audited with WHAT changed, never a self check-in value.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.database import get_db
from app.models.ops_files import OpsChecklistTemplate
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ops_packs import ChecklistIn, PackConfigPut, SelfCheckInPut
from app.services import ops_pack_catalog as packs
from app.services import ops_pack_seed, ops_self_check_in
from app.services.authz_service import has_capability, require_capability

router = APIRouter(tags=["operations"])

_read = require_capability("ops.read", "ops.manage")
_manage = require_capability("ops.manage")


def _pack(db: Session, tenant_id: str) -> tuple[Tenant, str]:
    tenant = db.get(Tenant, tenant_id)
    pack = packs.pack_for_business_type(tenant.business_type if tenant else None)
    if pack is None:
        raise HTTPException(status_code=409, detail="Choose your type of business in Settings > Workspace first.")
    return tenant, pack


def _property(db: Session, tenant_id: str, property_id: str | None) -> str | None:
    if property_id is None:
        return None
    if db.query(Property.id).filter_by(id=property_id, tenant_id=tenant_id).first() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return property_id


def _checklist_out(db: Session, tenant_id: str, pack: str, kind: str, property_id: str | None) -> dict:
    """Reads only: the property's copy, else the business's row, else the pack's default (not created on a read)."""
    q = db.query(OpsChecklistTemplate).filter_by(tenant_id=tenant_id, pack=pack, kind=kind)
    own = q.filter_by(property_id=property_id).first() if property_id else None
    base = own or q.filter(OpsChecklistTemplate.property_id.is_(None)).first()
    spec = packs.get(pack)["checklists"][kind]
    return {
        "kind": kind,
        "name": base.name if base else spec["name"],
        "items": list(base.items) if base else spec["items"],
        "property_id": property_id,
        "own_copy": own is not None,
    }


def _kind(pack: str, kind: str) -> str:
    if kind not in packs.get(pack)["checklists"]:
        raise HTTPException(status_code=404, detail="This business has no such checklist")
    return kind


@router.get("/ops/pack")
def get_pack(user: User = Depends(_read), db: Session = Depends(get_db)):
    tenant, pack = _pack(db, user.tenant_id)
    spec = packs.get(pack)
    overrides = ops_pack_seed.property_overrides(db, user.tenant_id, pack)
    cfg = ops_pack_seed.config(db, user.tenant_id, pack)
    return {
        "business_type": tenant.business_type,
        "pack": pack,
        "label": spec["label"],
        "flow": cfg["flow"],
        "flows": list(spec["flows"]),
        "machine": packs.machine(pack),
        "room_board": packs.FLOWS[cfg["flow"]]["room_board"],
        "unit_word": packs.unit_word_for(tenant.business_type) or spec["unit_word"],
        "file_word": spec["file_word"],
        "host_label": spec["host_label"],
        "step_names": list(spec["step_names"]),
        "self_check_in": {"offered": packs.flow_of(pack) == "whole_unit", "suggested": bool(spec["self_check_in"])},
        "config": cfg,
        "checklists": [
            {**_checklist_out(db, user.tenant_id, pack, kind, None), "property_copies": overrides.get(kind, [])}
            for kind in spec["checklists"]
        ],
    }


@router.put("/ops/pack/config")
def put_pack_config(body: PackConfigPut, user: User = Depends(_manage), db: Session = Depends(get_db)):
    _, pack = _pack(db, user.tenant_id)
    spec = packs.get(pack)
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    if "flow" in patch and patch["flow"] not in spec["flows"]:
        raise HTTPException(status_code=422, detail=f"flow must be one of {list(spec['flows'])} for this business")
    timings = {}
    for kind, t in (patch.pop("auto_messages", None) or {}).items():
        default = spec["auto_messages"].get(kind)
        if default is None:
            raise HTTPException(status_code=422, detail=f"Unknown automatic message: {kind}")
        field = "day" if default["when"] == "stay_day" else "hours"
        if t.get(field) is None:
            raise HTTPException(status_code=422, detail=f"{kind} is set in {field}")
        timings[kind] = {field: t[field]}
    if timings:
        patch["auto_messages"] = timings
    cfg = ops_pack_seed.save_config(db, user.tenant_id, pack, patch)
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.pack.config_changed",
        actor_user_id=user.id,
        target_type="ops_settings",
        target_id=pack,
        payload={"pack": pack, "changed": sorted(patch)},
    )
    db.commit()
    return cfg


@router.get("/ops/pack/checklists/{kind}")
def get_checklist(
    kind: str,
    property_id: str | None = Query(default=None),
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    _, pack = _pack(db, user.tenant_id)
    return _checklist_out(db, user.tenant_id, pack, _kind(pack, kind), _property(db, user.tenant_id, property_id))


@router.put("/ops/pack/checklists/{kind}")
def put_checklist(
    kind: str,
    body: ChecklistIn,
    property_id: str | None = Query(default=None),
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    _, pack = _pack(db, user.tenant_id)
    pid = _property(db, user.tenant_id, property_id)
    t = ops_pack_seed.save_template(
        db, user.tenant_id, pack, _kind(pack, kind), body.name, [i.model_dump() for i in body.items], pid
    )
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action="ops.checklist.updated",
        actor_user_id=user.id,
        target_type="ops_checklist_template",
        target_id=t.id,
        payload={"pack": pack, "kind": kind, "property_id": pid, "items": len(body.items)},
    )
    db.commit()
    return _checklist_out(db, user.tenant_id, pack, kind, pid)


@router.delete("/ops/pack/checklists/{kind}")
def reset_checklist(
    kind: str,
    property_id: str = Query(...),
    user: User = Depends(_manage),
    db: Session = Depends(get_db),
):
    _, pack = _pack(db, user.tenant_id)
    pid = _property(db, user.tenant_id, property_id)
    if ops_pack_seed.reset_property_template(db, user.tenant_id, pack, _kind(pack, kind), pid):
        append_audit(
            db,
            tenant_id=user.tenant_id,
            action="ops.checklist.reset",
            actor_user_id=user.id,
            target_type="property",
            target_id=pid,
            payload={"pack": pack, "kind": kind},
        )
    db.commit()
    return _checklist_out(db, user.tenant_id, pack, kind, pid)


@router.get("/ops/properties/{property_id}/self-check-in")
def get_self_check_in(property_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    reveal = has_capability(db, user, "ops.manage")
    return ops_self_check_in.view(db, user.tenant_id, property_id, reveal=reveal)


@router.put("/ops/properties/{property_id}/self-check-in")
def put_self_check_in(
    property_id: str, body: SelfCheckInPut, user: User = Depends(_manage), db: Session = Depends(get_db)
):
    values = body.model_dump(exclude_unset=True)
    enabled = values.pop("enabled", None)
    changed = ops_self_check_in.update(db, user.tenant_id, property_id, enabled=enabled, values=values)
    if changed:
        append_audit(
            db,
            tenant_id=user.tenant_id,
            action="ops.self_check_in.changed",
            actor_user_id=user.id,
            target_type="property",
            target_id=property_id,
            payload={"changed": changed},  # names only, never the code or steps
        )
    db.commit()
    return ops_self_check_in.view(db, user.tenant_id, property_id, reveal=True)
