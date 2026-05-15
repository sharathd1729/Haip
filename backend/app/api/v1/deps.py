from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db, set_tenant_context
from app.core.security import decode_token
from app.core.config import settings
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
# Same scheme but won't raise 401 if Authorization header is missing
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # ── Dev / demo bypass ─────────────────────────────────────────────────────
    # The frontend sets accessToken="demo" for demo-mode logins.
    # Resolve to the user whose tenant has the most recent call — this ensures
    # uploaded test recordings are always accessible regardless of which account
    # was used to create them.
    if token == "demo" and settings.ENVIRONMENT in ("development", "dev", "local"):
        from sqlalchemy import text as _text

        # Prefer: user whose tenant has the most recently created call
        row = db.execute(_text("""
            SELECT u.id
            FROM users u
            INNER JOIN calls c ON c.tenant_id = u.tenant_id
            WHERE u.is_deleted = false AND u.is_active = true
            ORDER BY c.created_at DESC
            LIMIT 1
        """)).first()

        demo_user = db.query(User).filter_by(id=row[0]).first() if row else None

        # Fallback: most recently registered active user
        if not demo_user:
            demo_user = (
                db.query(User)
                .filter_by(is_deleted=False, is_active=True)
                .order_by(User.created_at.desc())
                .first()
            )

        if demo_user:
            set_tenant_context(db, demo_user.tenant_id)
            return demo_user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Demo mode: no users in DB. Register at POST /api/v1/auth/register first.",
        )

    # ── Real JWT path ─────────────────────────────────────────────────────────
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        # In development, an expired/invalid JWT falls through to the demo bypass
        # so developers don't have to re-login every 15 minutes.
        if settings.ENVIRONMENT in ("development", "dev", "local"):
            from sqlalchemy import text as _text2
            row = db.execute(_text2("""
                SELECT u.id FROM users u
                INNER JOIN calls c ON c.tenant_id = u.tenant_id
                WHERE u.is_deleted = false AND u.is_active = true
                ORDER BY c.created_at DESC LIMIT 1
            """)).first()
            fallback = db.query(User).filter_by(id=row[0]).first() if row else None
            if not fallback:
                fallback = (
                    db.query(User)
                    .filter_by(is_deleted=False, is_active=True)
                    .order_by(User.created_at.desc())
                    .first()
                )
            if fallback:
                set_tenant_context(db, fallback.tenant_id)
                return fallback
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
    # Reuse the same resolution logic
    # Create a fake version of get_current_user by calling it with the resolved token
    from fastapi.security import OAuth2PasswordBearer as _OAuth2
    # Just inline the same logic rather than calling get_current_user to avoid DI issues
    if not token:
        # In dev mode, fall through to demo user
        if settings.ENVIRONMENT in ("development", "dev", "local"):
            from sqlalchemy import text as _text
            row = db.execute(_text("""
                SELECT u.id FROM users u
                INNER JOIN calls c ON c.tenant_id = u.tenant_id
                WHERE u.is_deleted = false AND u.is_active = true
                ORDER BY c.created_at DESC LIMIT 1
            """)).first()
            fallback = db.query(User).filter_by(id=row[0]).first() if row else None
            if not fallback:
                fallback = (
                    db.query(User)
                    .filter_by(is_deleted=False, is_active=True)
                    .order_by(User.created_at.desc())
                    .first()
                )
            if fallback:
                set_tenant_context(db, fallback.tenant_id)
                return fallback
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if token == "demo" and settings.ENVIRONMENT in ("development", "dev", "local"):
        from sqlalchemy import text as _text2
        row = db.execute(_text2("""
            SELECT u.id FROM users u
            INNER JOIN calls c ON c.tenant_id = u.tenant_id
            WHERE u.is_deleted = false AND u.is_active = true
            ORDER BY c.created_at DESC LIMIT 1
        """)).first()
        demo_user = db.query(User).filter_by(id=row[0]).first() if row else None
        if not demo_user:
            demo_user = (
                db.query(User)
                .filter_by(is_deleted=False, is_active=True)
                .order_by(User.created_at.desc())
                .first()
            )
        if demo_user:
            set_tenant_context(db, demo_user.tenant_id)
            return demo_user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Demo mode: no users in DB")

    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        if settings.ENVIRONMENT in ("development", "dev", "local"):
            from sqlalchemy import text as _text3
            row = db.execute(_text3("""
                SELECT u.id FROM users u
                INNER JOIN calls c ON c.tenant_id = u.tenant_id
                WHERE u.is_deleted = false AND u.is_active = true
                ORDER BY c.created_at DESC LIMIT 1
            """)).first()
            fallback = db.query(User).filter_by(id=row[0]).first() if row else None
            if not fallback:
                fallback = (
                    db.query(User)
                    .filter_by(is_deleted=False, is_active=True)
                    .order_by(User.created_at.desc())
                    .first()
                )
            if fallback:
                set_tenant_context(db, fallback.tenant_id)
                return fallback
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
