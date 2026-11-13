"""Channel manager via Channex (services/channex_service.py). Owner / manager, module `channel_manager`.

  GET    /channex/status      connected?, base URL, each unit with its mapping and last push (or why it failed)
  POST   /channex/connect     {api_key, base_url?} checks the key against Channex, stores it encrypted (audited)
  DELETE /channex/connect     disconnect: key wiped, sync stops (audited); mappings and booking links are kept
  GET    /channex/remote      Channex properties with their room types and rate plans, to map units to
  PUT    /channex/mappings    {mappings: [{property_id, channex_property_id, channex_room_type_id, channex_rate_plan_id?,
                              push_rates}]} replaces the set (audited)
  POST   /channex/sync        queue a pull + push now (202)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_module, require_roles
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.user import User, UserRole

router = APIRouter(prefix="/channex", tags=["channel-manager"], dependencies=[Depends(require_module("channel_manager"))])
_staff = require_roles(UserRole.OWNER, UserRole.MANAGER)


class ConnectBody(BaseModel):
    api_key: str = Field(min_length=8, max_length=200)
    base_url: str | None = Field(default=None, max_length=200)


class MappingIn(BaseModel):
    property_id: str = Field(min_length=1, max_length=64)
    channex_property_id: str = Field(min_length=1, max_length=64)
    channex_room_type_id: str = Field(min_length=1, max_length=64)
    channex_rate_plan_id: str | None = Field(default=None, max_length=64)
    push_rates: bool = False


class MappingsBody(BaseModel):
    mappings: list[MappingIn] = Field(max_length=500)


def _iso(dt):
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat() if dt else None


@router.get("/status")
def status(user: User = Depends(_staff), db: Session = Depends(get_db)):
    from app.models.channex import ChannexMapping
    from app.models.property import Property
    from app.services import channex_service as svc

    integ = svc.integration(db, user.tenant_id)
    maps = {m.property_id: m for m in db.query(ChannexMapping).filter_by(tenant_id=user.tenant_id)}
    units = db.query(Property).filter_by(tenant_id=user.tenant_id, is_active=True).order_by(Property.name).all()
    return {
        "connected": bool(integ and integ.status == "active"),
        "base_url": (integ.config or {}).get("base_url") if integ else None,
        "units": [
            {
                "property_id": p.id, "name": p.name, "mapped": p.id in maps,
                "channex_property_id": maps[p.id].channex_property_id if p.id in maps else None,
                "channex_room_type_id": maps[p.id].channex_room_type_id if p.id in maps else None,
                "channex_rate_plan_id": maps[p.id].channex_rate_plan_id if p.id in maps else None,
                "push_rates": maps[p.id].push_rates if p.id in maps else False,
                "last_pushed_at": _iso(maps[p.id].last_pushed_at) if p.id in maps else None,
                "last_push_error": maps[p.id].last_push_error if p.id in maps else None,
            }
            for p in units
        ],
    }


@router.post("/connect")
def connect(body: ConnectBody, user: User = Depends(_staff), db: Session = Depends(get_db)):
    from app.adapters.pms.channex import ChannexClient, ChannexError
    from app.core.encryption import encrypt_credentials
    from app.models.integration import Integration
    from app.services import channex_service as svc

    try:
        client = ChannexClient(body.api_key.strip(), body.base_url)
        try:
            found = client.properties()
        finally:
            client.close()
    except ChannexError as exc:
        raise HTTPException(status_code=422, detail=f"Channex did not accept that: {exc}") from None
    integ = svc.integration(db, user.tenant_id)
    if integ is None:
        integ = Integration(tenant_id=user.tenant_id, kind=svc.KIND)
        db.add(integ)
    integ.credentials_kms_blob = encrypt_credentials({"api_key": body.api_key.strip()})
    integ.config = {**(integ.config or {}), "base_url": body.base_url or None}
    integ.status = "active"
    integ.installed_at = datetime.now(UTC).isoformat()
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="integration.connected",
                 target_type="integration", target_id=integ.id, payload={"kind": svc.KIND, "base_url": body.base_url})
    db.commit()
    return {"connected": True, "channex_properties": len(found)}


@router.delete("/connect")
def disconnect(user: User = Depends(_staff), db: Session = Depends(get_db)):
    from app.services import channex_service as svc

    integ = svc.integration(db, user.tenant_id)
    if integ is None:
        raise HTTPException(status_code=404, detail="Channex is not connected")
    integ.status, integ.credentials_kms_blob = "disconnected", None
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="integration.disconnected",
                 target_type="integration", target_id=integ.id, payload={"kind": svc.KIND})
    db.commit()
    return {"connected": False}


@router.get("/remote")
def remote(user: User = Depends(_staff), db: Session = Depends(get_db)):
    from app.adapters.pms.channex import ChannexError
    from app.services import channex_service as svc

    try:
        client = svc.client_for(db, user.tenant_id)
    except svc.NotConnected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    try:
        out = []
        for p in client.properties():
            out.append({"id": p["id"], "title": p.get("title"),
                        "room_types": [{"id": r["id"], "title": r.get("title")} for r in client.room_types(p["id"])],
                        "rate_plans": [{"id": r["id"], "title": r.get("title"), "room_type_id": r.get("room_type_id")}
                                       for r in client.rate_plans(p["id"])]})
        return {"properties": out}
    except ChannexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    finally:
        client.close()


@router.put("/mappings")
def put_mappings(body: MappingsBody, user: User = Depends(_staff), db: Session = Depends(get_db)):
    from app.models.channex import ChannexMapping
    from app.models.property import Property

    ids = [m.property_id for m in body.mappings]
    rooms = [m.channex_room_type_id for m in body.mappings]
    if len(set(ids)) != len(ids) or len(set(rooms)) != len(rooms):
        raise HTTPException(status_code=422, detail="Each unit and each Channex room type can be mapped only once.")
    own = {pid for (pid,) in db.query(Property.id).filter(Property.tenant_id == user.tenant_id, Property.id.in_(ids or ["-"]))}
    if set(ids) - own:
        raise HTTPException(status_code=404, detail="Unknown unit")
    db.query(ChannexMapping).filter_by(tenant_id=user.tenant_id).delete(synchronize_session=False)
    db.flush()
    for m in body.mappings:
        db.add(ChannexMapping(tenant_id=user.tenant_id, **m.model_dump()))
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="channex.mappings_changed",
                 target_type="integration", target_id=None, payload={"units": len(body.mappings)})
    db.commit()
    return {"mapped": len(body.mappings)}


@router.post("/sync", status_code=202)
def sync_now(user: User = Depends(_staff), db: Session = Depends(get_db)):
    from app.services import channex_service as svc
    from app.workers.tasks.channex_sync import sync_tenant

    integ = svc.integration(db, user.tenant_id)
    if integ is None or integ.status != "active":
        raise HTTPException(status_code=409, detail="Connect Channex first.")
    sync_tenant.delay(user.tenant_id)
    return {"queued": True}
