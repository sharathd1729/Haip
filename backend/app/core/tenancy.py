"""
Tenant context middleware (B7 — hardened).

Responsibilities:
  1. Attach tenant_id / user_id / role to request.state for use by
     structured logging and any middleware that runs after this one.
  2. Do NOT attempt to set the Postgres RLS variable here.

Why not set RLS here?
  Middleware runs on a different DB connection than the one injected by
  FastAPI's Depends(get_db) dependency.  Calling set_config() on a
  throwaway SessionLocal() would have zero effect on the connection that
  actually executes ORM queries.

  RLS context is set correctly in api/v1/deps.py → get_current_user()
  via database.set_tenant_context(db, user.tenant_id), which operates
  on the *same* SQLAlchemy session that the endpoint uses.

  database.set_tenant_context() uses a parameterised SELECT set_config()
  call (is_local=True) so the variable is:
    • transaction-scoped — no leakage between requests
    • injection-safe    — tenant_id is bound, never interpolated
"""
from fastapi import Request
from app.core.security import decode_token
import structlog

log = structlog.get_logger()

# Paths that do NOT require a tenant context (no JWT expected)
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

    # Extract bearer token — non-JWT requests (e.g. OPTIONS) pass through
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

    # Attach decoded claims to request.state for logging / other middleware
    request.state.tenant_id = tenant_id
    request.state.user_id = decoded.get("sub")
    request.state.role = decoded.get("role")

    return await call_next(request)
