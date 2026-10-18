"""
Workspace context endpoint — returns active modules + feature flags.
Frontend calls this once per session and stores in React context.
All subsequent rendering decisions are driven by this response.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.services.workspace_context import load_workspace_context

router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspaceContextResponse(BaseModel):
    workspace_id: str
    plan: str
    business_type: str | None = None   # caravan / villa_resort / homestay / hotel
    active_modules: list[str]
    flags: dict[str, bool]


@router.get("/context", response_model=WorkspaceContextResponse)
def get_workspace_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns active modules and feature flags.
    Frontend stores this in WorkspaceProvider context.
    TTL: client should cache for 5 minutes.
    """
    ctx = load_workspace_context(db, current_user.tenant_id)

    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()

    return WorkspaceContextResponse(
        workspace_id=current_user.tenant_id,
        plan=ctx.plan,
        business_type=tenant.business_type if tenant else None,
        active_modules=ctx.active_modules,
        flags=ctx.flags,
    )


@router.get("/modules")
def list_workspace_modules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All modules the workspace has subscribed to."""
    from app.models.module import Module, WorkspaceModule

    rows = (
        db.query(Module, WorkspaceModule)
        .join(WorkspaceModule, WorkspaceModule.module_id == Module.id)
        .filter(WorkspaceModule.workspace_id == current_user.tenant_id)
        .all()
    )
    return [
        {
            "code": mod.code,
            "name": mod.name,
            "description": mod.description,
            "category": mod.category,
            "status": mod.status,
            "enabled": wm.enabled,
            "activated_at": wm.activated_at,
            "expires_at": wm.expires_at,
        }
        for mod, wm in rows
    ]


@router.post("/modules/{module_code}/activate", status_code=201)
def activate_module(
    module_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable a module for this workspace. Owner only."""
    if current_user.role not in ("owner",):
        raise HTTPException(status_code=403, detail="owner_required")
    from app.workers.tasks.module_activation import activate
    activate.delay(workspace_id=current_user.tenant_id, module_code=module_code, activated_by=current_user.id)
    return {"module_code": module_code, "status": "activation_queued"}


@router.delete("/modules/{module_code}", status_code=200)
def deactivate_module(
    module_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable a module for this workspace. Owner only."""
    if current_user.role not in ("owner",):
        raise HTTPException(status_code=403, detail="owner_required")
    from app.workers.tasks.module_activation import deactivate
    deactivate.delay(workspace_id=current_user.tenant_id, module_code=module_code, deactivated_by=current_user.id)
    return {"module_code": module_code, "status": "deactivation_queued"}


@router.get("/flags")
def list_flags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolved feature flags for this workspace."""
    ctx = load_workspace_context(db, current_user.tenant_id)
    return {"flags": ctx.flags}


@router.put("/flags/{flag_key}")
def override_flag(
    flag_key: str,
    value: bool,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manual flag override. Owner only."""
    if current_user.role not in ("owner",):
        raise HTTPException(status_code=403, detail="owner_required")

    from app.models.feature_flag import FeatureFlag
    from app.models.base import gen_uuid

    existing = (
        db.query(FeatureFlag)
        .filter(
            FeatureFlag.flag_key == flag_key,
            FeatureFlag.workspace_id == current_user.tenant_id,
        )
        .first()
    )
    if existing:
        existing.value = value
        existing.source = "manual"
        existing.set_by = current_user.id
    else:
        db.add(FeatureFlag(
            id=gen_uuid(),
            flag_key=flag_key,
            workspace_id=current_user.tenant_id,
            value=value,
            source="manual",
            set_by=current_user.id,
        ))
    db.commit()
    return {"flag_key": flag_key, "value": value, "source": "manual"}
