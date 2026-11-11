"""HAIP Calls app (Android), step 1 (docs/MOBILE_CALL_TRACKING_SPEC.md).

  POST   /devices/register   logged-in user: register this phone, returns the device token ONCE
  PUT    /devices/settings   device token: unknown-number rule, working hours, personal numbers (stored as hashes)
  GET    /devices            owner/manager: every staff device in the workspace
  DELETE /devices/{id}       revoke: your own device, or any device for owner/manager (audited)
  POST   /device-calls       device token: up to 200 call-log entries, idempotent on (device, device_call_id)

Device-token requests send "Authorization: Bearer haip_dev_..."; unknown or revoked token = 401.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db, set_tenant_context
from app.models.mobile_device import MobileDevice
from app.models.user import User, UserRole
from app.schemas.mobile_device import DeviceCallBatch, DeviceRegister, DeviceSettings
from app.services import mobile_device_service

router = APIRouter(prefix="/devices", tags=["calls-app"])
calls_router = APIRouter(prefix="/device-calls", tags=["calls-app"])

_MANAGERS = (UserRole.OWNER, UserRole.MANAGER)


def current_device(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> MobileDevice:
    raw = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    device = mobile_device_service.authenticate(db, raw)
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked device token",
                            headers={"WWW-Authenticate": "Bearer"})
    return device


def _out(d: MobileDevice, user_name: str | None = None) -> dict:
    return {
        "id": d.id, "device_id": d.device_id, "user_id": d.user_id, "user_name": user_name,
        "model": d.model, "android_version": d.android_version, "app_version": d.app_version,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "revoked": d.revoked_at is not None,
        "settings": mobile_device_service.settings_out(d),
    }


@router.post("/register", status_code=201)
def register_device(body: DeviceRegister, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    device, raw = mobile_device_service.register(db, current_user, body)
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    db.refresh(device)
    # The raw token is returned this once and never stored.
    return {**_out(device, current_user.name), "token": raw}


@router.put("/settings")
def update_settings(body: DeviceSettings, device: MobileDevice = Depends(current_device), db: Session = Depends(get_db)):
    mobile_device_service.apply_settings(db, device, body)
    db.commit()
    set_tenant_context(db, device.tenant_id)
    return mobile_device_service.settings_out(device)


@router.get("")
def list_devices(current_user: User = Depends(require_roles(*_MANAGERS)), db: Session = Depends(get_db)):
    rows = (db.query(MobileDevice, User.name).outerjoin(User, User.id == MobileDevice.user_id)
            .filter(MobileDevice.tenant_id == current_user.tenant_id)
            .order_by(MobileDevice.created_at.desc()).all())
    return {"devices": [_out(d, name) for d, name in rows]}


@router.delete("/{device_pk}", status_code=204)
def revoke_device(device_pk: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    device = db.query(MobileDevice).filter_by(id=device_pk, tenant_id=current_user.tenant_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.user_id != current_user.id and current_user.role not in _MANAGERS:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    mobile_device_service.revoke(db, device, current_user)
    db.commit()


@calls_router.post("")
def upload_device_calls(body: DeviceCallBatch, device: MobileDevice = Depends(current_device), db: Session = Depends(get_db)):
    results = mobile_device_service.upload_calls(db, device, body)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"results": results, "counts": counts}
