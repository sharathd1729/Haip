from __future__ import annotations

from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db, set_tenant_context
from app.core.security import decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
# Same scheme but won't raise 401 if Authorization header is missing
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


WORKSPACE_HEADER = "X-HAIP-Workspace"
_SLUGS: dict[str, tuple[float, str | None]] = {}   # tenant_id -> (fetched at, slug); slugs change rarely
_SLUG_TTL = 300.0


def _tenant_slug(db: Session, tenant_id: str) -> str | None:
    import time

    from app.models.tenant import Tenant

    hit = _SLUGS.get(tenant_id)
    if hit and time.monotonic() - hit[0] < _SLUG_TTL:
        return hit[1]
    slug = db.query(Tenant.slug).filter(Tenant.id == tenant_id).scalar()
    _SLUGS[tenant_id] = (time.monotonic(), slug)
    return slug


def check_workspace(request: Request | None, db: Session, user: User) -> None:
    """Workspace redesign Phase 0: a page at /w/<slug>/... sends that slug in X-HAIP-Workspace (frontend lib/api.ts).
    If it names another workspace than the signed-in one (a tab left open on workspace A after signing in to B, or a
    pasted link), refuse with 409 ``wrong_workspace`` instead of quietly showing or changing B's data under A's address.
    No header (other pages, scripts, the public API, the mobile app) = no check; data is always the token's tenant."""
    wanted = (request.headers.get(WORKSPACE_HEADER) or "").strip().lower() if request is not None else ""
    if not wanted:
        return
    mine = _tenant_slug(db, user.tenant_id)
    if mine and wanted != mine.lower():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"error": "wrong_workspace", "message": "This page belongs to another workspace.",
                                    "workspace": mine})


def get_current_user(
    request: Request = None,  # FastAPI injects it; None when called directly (auth.py)
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False, is_active=True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    set_tenant_context(db, user.tenant_id)
    check_workspace(request, db, user)
    return user


def get_current_user_flexible(
    request: Request,
    header_token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User:
    """
    Like get_current_user but also accepts a ?token= query parameter.
    Used by endpoints (e.g. audio streaming) where the browser can't
    set an Authorization header.
    """
    token = header_token or request.query_params.get("token") or ""

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False, is_active=True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    set_tenant_context(db, user.tenant_id)
    check_workspace(request, db, user)
    return user


def require_roles(*roles):
    def _check(current_user: User = Depends(get_current_user)):
        if current_user.role.value not in [r.value if hasattr(r, "value") else r for r in roles]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return _check


# ─── Module-driven guards ─────────────────────────────────────────────────────

def get_workspace_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    FastAPI dependency: returns WorkspaceContext for the current user's workspace.
    L1 Redis cache (5 min TTL) → DB fallback.

    Every tenant is provisioned with workspace_modules rows at creation time
    (provision_default_modules(), called from /auth/register) and existing
    tenants were backfilled in migration 035 — so a workspace with zero rows
    today is a genuine anomaly (provisioning failed/was skipped), not the
    normal "not yet backfilled" case. Fail closed: no active modules until
    someone provisions the workspace, rather than granting full access.
    """
    from app.services.workspace_context import load_workspace_context, WorkspaceContext
    from app.models.module import WorkspaceModule
    from app.core.cache import ctx_get, ctx_set

    wid = current_user.tenant_id

    # L1 cache hit
    cached = ctx_get(wid)
    if cached:
        return WorkspaceContext(
            workspace_id=cached["workspace_id"],
            active_modules=cached["active_modules"],
            flags=cached["flags"],
            plan=cached["plan"],
        )

    has_any_modules = db.query(WorkspaceModule).filter(
        WorkspaceModule.workspace_id == wid
    ).first()

    if not has_any_modules:
        import structlog
        structlog.get_logger().error("workspace_unprovisioned", workspace_id=wid)
        ctx = WorkspaceContext(workspace_id=wid, active_modules=[], flags={}, plan="growth")
    else:
        ctx = load_workspace_context(db, wid)

    # Populate L1 cache
    ctx_set(wid, {
        "workspace_id": ctx.workspace_id,
        "active_modules": ctx.active_modules,
        "flags": ctx.flags,
        "plan": ctx.plan,
    })
    return ctx


def require_module(*module_codes: str):
    """
    Route dependency factory.  Raises 403 with upgrade hint if ANY required
    module is not active for this workspace.

    Usage:
        @router.get("/endpoint")
        def my_endpoint(ctx = Depends(require_module("calls", "analytics"))):
            ...
    """
    def _guard(
        ctx=Depends(get_workspace_context),
        current_user: User = Depends(get_current_user),
    ):
        missing = [m for m in module_codes if m not in ctx.active_modules]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "module_not_enabled",
                    "missing_modules": missing,
                    "message": f"This feature requires modules: {', '.join(missing)}. "
                               "Contact your HAIP account manager to upgrade.",
                },
            )
        return ctx
    return _guard


def require_flag(*flag_keys: str):
    """
    Route dependency factory.  Raises 403 if ANY required feature flag is False.

    Usage:
        @router.get("/endpoint")
        def my_endpoint(ctx = Depends(require_flag("forecasting_enabled"))):
            ...
    """
    def _guard(ctx=Depends(get_workspace_context)):
        missing = [f for f in flag_keys if not ctx.flag(f)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "feature_not_enabled",
                    "missing_flags": missing,
                    "message": f"Feature flags required: {', '.join(missing)}.",
                },
            )
        return ctx
    return _guard
