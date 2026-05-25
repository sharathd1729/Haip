from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text as _sql
from app.core.database import get_db, set_tenant_context
from app.core.security import decode_token
from app.core.config import settings
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
# Same scheme but won't raise 401 if Authorization header is missing
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Environments where the dev bypass is allowed.
# Production and staging must NEVER be in this set.
_DEV_ENVIRONMENTS = {"development", "dev", "local"}


def _is_dev() -> bool:
    """Return True only if running in a known development environment."""
    return settings.ENVIRONMENT in _DEV_ENVIRONMENTS


def _get_dev_user(db: Session) -> User | None:
    """
    Resolve a fallback user for dev/demo mode.
    Prefers the user whose tenant has the most recent call (so uploaded test
    recordings are always accessible). Falls back to the most recently
    registered active user.
    """
    row = db.execute(_sql("""
        SELECT u.id
        FROM users u
        INNER JOIN calls c ON c.tenant_id = u.tenant_id
        WHERE u.is_deleted = false AND u.is_active = true
        ORDER BY c.created_at DESC
        LIMIT 1
    """)).first()

    user = db.query(User).filter_by(id=row[0]).first() if row else None
    if not user:
        user = (
            db.query(User)
            .filter_by(is_deleted=False, is_active=True)
            .order_by(User.created_at.desc())
            .first()
        )
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # ── Dev / demo bypass ─────────────────────────────────────────────────────
    # The frontend sets accessToken="demo" for demo-mode logins.
    # Only active in known development environments — NEVER in production.
    if token in ("demo", "owner-bypass") and _is_dev():
        dev_user = _get_dev_user(db)
        if dev_user:
            set_tenant_context(db, dev_user.tenant_id)
            return dev_user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dev bypass: no users in DB. Register at POST /api/v1/auth/register first.",
        )

    # ── Real JWT path ─────────────────────────────────────────────────────────
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        # In development, an expired/invalid JWT falls through to the dev bypass
        # so developers don't have to re-login every 15 minutes.
        if _is_dev():
            dev_user = _get_dev_user(db)
            if dev_user:
                set_tenant_context(db, dev_user.tenant_id)
                return dev_user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False, is_active=True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Set RLS context
    set_tenant_context(db, user.tenant_id)

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
        if _is_dev():
            dev_user = _get_dev_user(db)
            if dev_user:
                set_tenant_context(db, dev_user.tenant_id)
                return dev_user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if token in ("demo", "owner-bypass") and _is_dev():
        dev_user = _get_dev_user(db)
        if dev_user:
            set_tenant_context(db, dev_user.tenant_id)
            return dev_user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dev bypass: no users in DB")

    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        if _is_dev():
            dev_user = _get_dev_user(db)
            if dev_user:
                set_tenant_context(db, dev_user.tenant_id)
                return dev_user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter_by(id=decoded["sub"], is_deleted=False, is_active=True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    set_tenant_context(db, user.tenant_id)
    return user


def require_roles(*roles):
    def _check(current_user: User = Depends(get_current_user)):
        if current_user.role.value not in [r.value if hasattr(r, "value") else r for r in roles]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return _check
