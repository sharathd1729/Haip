"""Manage API keys for the public API (Settings > Developers).

  GET    /api-keys          list keys (never the secret)
  POST   /api-keys          create a key; the raw key is returned once
  DELETE /api-keys/{id}     revoke

Only owners create or revoke keys: a key with bookings:read exposes guest contact details.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.config import settings
from app.core.database import get_db, set_tenant_context
from app.models.api_key import ApiKey
from app.models.user import User, UserRole
from app.services import api_key_service

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

_MAX_ACTIVE_KEYS = 20


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    expires_in_days: Optional[int] = Field(None, ge=1, le=730)


def _out(k: ApiKey) -> dict:
    return {
        "id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes or [],
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "revoked": k.revoked_at is not None,
    }


@router.get("")
def list_keys(current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)), db: Session = Depends(get_db)):
    keys = db.query(ApiKey).filter_by(tenant_id=current_user.tenant_id).order_by(ApiKey.created_at.desc()).all()
    return {
        "keys": [_out(k) for k in keys],
        "scopes": [{"scope": s, "description": d} for s, d in api_key_service.SCOPES.items()],
        "docs_url": f"{settings.API_BASE_URL.rstrip('/')}/api/public/v1/docs",
        "openapi_url": f"{settings.API_BASE_URL.rstrip('/')}/api/public/v1/openapi.json",
    }


@router.post("", status_code=201)
def create_key(body: KeyCreate, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    unknown = [s for s in body.scopes if s not in api_key_service.SCOPES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown scope: {', '.join(unknown)}")
    active = db.query(ApiKey).filter(ApiKey.tenant_id == current_user.tenant_id, ApiKey.revoked_at.is_(None)).count()
    if active >= _MAX_ACTIVE_KEYS:
        raise HTTPException(status_code=422, detail=f"You can have at most {_MAX_ACTIVE_KEYS} active keys. Revoke one you no longer use.")
    row, raw = api_key_service.create_key(db, current_user.tenant_id, body.name, body.scopes, current_user.id, body.expires_in_days)
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="api_key.created",
                 target_type="api_key", target_id=row.id, payload={"name": row.name, "scopes": row.scopes})
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    db.refresh(row)
    # The raw key is returned this once and never stored.
    return {**_out(row), "key": raw}


@router.delete("/{key_id}", status_code=204)
def revoke_key(key_id: str, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    key = db.query(ApiKey).filter_by(id=key_id, tenant_id=current_user.tenant_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="api_key.revoked",
                     target_type="api_key", target_id=key.id, payload={"name": key.name})
        db.commit()
