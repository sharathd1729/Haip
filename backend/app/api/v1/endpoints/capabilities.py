"""Capability catalogue + per-tenant role matrix (HAIP_MCP_Connector_Plan.md
Phase 1, ticket 1.6). The matrix is the thing that actually gates access
(via authz_service.get_capabilities) -- this router is how an owner views
and edits it."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.cache import invalidate_tenant
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.capability import Capability, RoleCapability
from app.models.user import User, UserRole
from app.schemas.capability import (
    CapabilityOut,
    RoleCapabilityOut,
    RoleCapabilityMatrix,
    RoleCapabilityMatrixUpdate,
)
from app.services import authz_service

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=list[CapabilityOut])
def list_catalogue(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The global capability catalogue -- descriptive metadata only
    (label/category/risk), not tenant-scoped, available to any authed role."""
    return db.query(Capability).order_by(Capability.category, Capability.key).all()


@router.get("/mine", response_model=list[CapabilityOut])
def list_my_capabilities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """4.2: 'what can a token created by me actually do' -- the full
    /matrix endpoint is owner-only (it exposes every role's grants), but a
    manager can also mint an MCP token (Phase 0 ticket 0.6) and needs to
    see their OWN capability set to answer that question. Narrower
    disclosure than /matrix: only the caller's own granted keys, via the
    same authz_service every enforcement path reads."""
    granted = authz_service.get_capabilities(db, current_user)
    if not granted:
        return []
    return (
        db.query(Capability)
        .filter(Capability.key.in_(granted))
        .order_by(Capability.category, Capability.key)
        .all()
    )


@router.get("/matrix", response_model=RoleCapabilityMatrix)
def get_matrix(
    current_user: User = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    """Full tenant role x capability matrix, every cell present (not just
    granted ones) so the settings UI can render every toggle."""
    rows = db.query(RoleCapability).filter_by(tenant_id=current_user.tenant_id).all()
    if not rows:
        raise HTTPException(status_code=409, detail="Tenant capability matrix is unprovisioned")
    return RoleCapabilityMatrix(entries=[RoleCapabilityOut.model_validate(r) for r in rows])


@router.put("/matrix", response_model=RoleCapabilityMatrix)
def update_matrix(
    body: RoleCapabilityMatrixUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    """Applies the given (role, capability_key) -> allowed edits. Writes one
    AuditEvent per call (not per cell) with the full edit list as payload --
    this is the DPDP-relevant paper trail for who changed access and when."""
    valid_roles = {r.value for r in UserRole}
    valid_keys = {k for (k,) in db.query(Capability.key).all()}

    for edit in body.edits:
        if edit.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Unknown role: {edit.role}")
        if edit.capability_key not in valid_keys:
            raise HTTPException(status_code=400, detail=f"Unknown capability: {edit.capability_key}")

    applied = []
    for edit in body.edits:
        row = (
            db.query(RoleCapability)
            .filter_by(tenant_id=current_user.tenant_id, role=edit.role, capability_key=edit.capability_key)
            .first()
        )
        if row is None:
            # Matrix cell was missing (shouldn't happen post-seed, but don't
            # silently no-op an owner's explicit edit) -- create it.
            row = RoleCapability(
                tenant_id=current_user.tenant_id, role=edit.role,
                capability_key=edit.capability_key, allowed=edit.allowed,
            )
            db.add(row)
        else:
            row.allowed = edit.allowed
        applied.append({"role": edit.role, "capability_key": edit.capability_key, "allowed": edit.allowed})

    append_audit(
        db,
        tenant_id=current_user.tenant_id,
        action="role_capabilities.change",
        actor_user_id=current_user.id,
        target_type="role_capabilities",
        target_id=current_user.tenant_id,
        payload={"edits": applied},
    )
    db.commit()

    invalidate_tenant(current_user.tenant_id)

    rows = db.query(RoleCapability).filter_by(tenant_id=current_user.tenant_id).all()
    return RoleCapabilityMatrix(entries=[RoleCapabilityOut.model_validate(r) for r in rows])
