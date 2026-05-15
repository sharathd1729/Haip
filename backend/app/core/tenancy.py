"""
Tenant context middleware.
Extracts tenant_id from the JWT access token on every request and sets
the Postgres session variable `app.tenant_id` so RLS policies fire correctly.
"""
from fastapi import Request, HTTPException, status
from sqlalchemy import text
from app.core.database import SessionLocal
from app.core.security import decode_token
import structlog

log = structlog.get_logger()

# Paths that do NOT require a tenant context
_PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/webhooks/",   # webhooks use shared-secret auth, not JWT
)


async def tenant_context_middleware(request: Request, call_next):
    path = request.url.path

    # Skip public routes
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    # Extract bearer token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return await call_next(request)

    token = auth_header.removeprefix("Bearer ").strip()
    decoded = decode_token(token)

    if not decoded or decoded.get("type") != "access":
        return await call_next(request)

    tenant_id = decoded.get("tenant_id")
    if not tenant_id:
        return await call_next(request)

    # Attach to request state for downstream access
    request.state.tenant_id = tenant_id
    request.state.user_id = decoded.get("sub")
    request.state.role = decoded.get("role")

    # Set Postgres session variable for RLS — use a fresh db connection
    db = SessionLocal()
    try:
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        db.commit()
    except Exception:
        pass
    finally:
        db.close()

    return await call_next(request)
