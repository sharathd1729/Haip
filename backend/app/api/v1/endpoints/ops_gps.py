"""Ops GPS API (migration 181). ops.read views, ops.manage configures.

Settings  GET|PUT /ops/gps/settings · POST /ops/gps/settings/rotate-secret (the webhook secret is returned ONCE)
Trackers  GET|POST /ops/gps/devices · PATCH|DELETE /ops/gps/devices/{id}
Map       GET /ops/gps/live · GET /ops/gps/files/{file_id}/track
Route     PUT /ops/gps/files/{file_id}/route · POST /ops/gps/alerts/{item_id}/approve-detour
Every write is audited (ops.gps.*). Positions arrive at /webhooks/gps/{slug} (webhooks_gps.py) or by polling.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.gps import ConnectionIn, DetourIn, DeviceIn, DevicePatch, RouteIn
from app.services import gps_alerts, gps_service
from app.services.authz_service import require_capability

router = APIRouter(prefix="/ops/gps", tags=["operations"])

_read = require_capability("ops.read", "ops.manage")
_manage = require_capability("ops.manage")


@router.get("/settings")
def get_settings(user: User = Depends(_manage), db: Session = Depends(get_db)):
    return gps_service.connection(db, user.tenant_id)


@router.put("/settings")
def save_settings(body: ConnectionIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    out = gps_service.save_connection(db, user.tenant_id, body, user.id)
    db.commit()
    return out


@router.post("/settings/rotate-secret")
def rotate_secret(user: User = Depends(_manage), db: Session = Depends(get_db)):
    out = gps_service.rotate_secret(db, user.tenant_id, user.id)
    db.commit()
    return out


@router.get("/devices")
def list_devices(user: User = Depends(_read), db: Session = Depends(get_db)):
    return gps_service.list_devices(db, user.tenant_id)


@router.post("/devices", status_code=201)
def create_device(body: DeviceIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    out = gps_service.create_device(db, user.tenant_id, body, user.id)
    db.commit()
    return out


@router.patch("/devices/{device_id}")
def update_device(device_id: str, body: DevicePatch, user: User = Depends(_manage), db: Session = Depends(get_db)):
    out = gps_service.update_device(db, user.tenant_id, device_id, body, user.id)
    db.commit()
    return out


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: str, user: User = Depends(_manage), db: Session = Depends(get_db)):
    gps_service.delete_device(db, user.tenant_id, device_id, user.id)
    db.commit()
    return Response(status_code=204)


@router.get("/live")
def live(user: User = Depends(_read), db: Session = Depends(get_db)):
    return gps_service.live(db, user.tenant_id)


@router.get("/files/{file_id}/track")
def track(file_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    return gps_service.track(db, user.tenant_id, file_id)


@router.put("/files/{file_id}/route")
def set_route(file_id: str, body: RouteIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    out = gps_service.set_route(db, user.tenant_id, file_id, body, user.id)
    db.commit()
    return out


@router.post("/alerts/{item_id}/approve-detour")
def approve_detour(item_id: str, body: DetourIn, user: User = Depends(_manage), db: Session = Depends(get_db)):
    item = gps_alerts.approve_detour(db, user.tenant_id, item_id, body.reason, user.id)
    db.commit()
    return {"id": item.id, "status": item.status}
