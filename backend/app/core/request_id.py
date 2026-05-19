"""
Request-ID middleware (B16).

Assigns a sortable, unique request ID to every HTTP request:
  - Reads the incoming X-Request-ID header (so upstream proxies can set it)
  - Falls back to generating a compact timestamp-prefixed hex ID
  - Binds the ID to the structlog context-var so every log line in
    that request's thread/async-task automatically includes it
  - Echoes the ID back via X-Request-ID response header
  - Exposes _request_id_ctx_var so Celery tasks can inherit it

Format (when self-generated):
  <10-char hex timestamp ms><16-char random hex>  — 26 chars total, lexicographically sortable
  Example: "0190a3b5c2e1" + "8f3d2a1b9c4e5f6a"  → "0190a3b5c2e18f3d2a1b9c4e5f6a"

Why not python-ulid?
  We deliberately avoid adding a dependency here — the format above is
  compact, sortable by time, and URL-safe without any extras.
"""

import time
import uuid
import contextvars
from fastapi import Request
from starlette.responses import Response
import structlog

log = structlog.get_logger()

# Context variable holding the current request ID
# Workers inherit this when Celery tasks are dispatched on the same thread
_request_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

# Header name (standard de-facto)
REQUEST_ID_HEADER = "X-Request-ID"
_MAX_INCOMING_ID_LEN = 64


def _generate_request_id() -> str:
    """Generate a 26-char sortable request ID (no external deps)."""
    ts_hex = format(int(time.time() * 1000), "012x")   # 12 hex chars ≈ ms timestamp
    rand_hex = uuid.uuid4().hex[:14]                    # 14 random hex chars
    return ts_hex + rand_hex                             # 26 chars total


def get_request_id() -> str:
    """Return the current request ID, or empty string if none set."""
    return _request_id_ctx_var.get("")


async def request_id_middleware(request: Request, call_next):
    """
    FastAPI middleware that:
      1. Reads or generates X-Request-ID
      2. Stores it in the context-var
      3. Binds it (plus tenant_id / user_id from state) to structlog
      4. Adds X-Request-ID to the response headers
    """
    # Prefer upstream-provided ID; validate length to prevent log injection
    incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if incoming and len(incoming) <= _MAX_INCOMING_ID_LEN:
        request_id = incoming
    else:
        request_id = _generate_request_id()

    # Store in context-var (available to any code in this async task)
    token = _request_id_ctx_var.set(request_id)

    # Bind to structlog context-vars — cleared automatically per-request
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    # Also bind tenant/user if tenancy middleware has already decoded the JWT
    # (tenancy middleware runs before this one, so request.state may be set)
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    if tenant_id:
        structlog.contextvars.bind_contextvars(tenant_id=tenant_id)
    if user_id:
        structlog.contextvars.bind_contextvars(user_id=user_id)

    try:
        response: Response = await call_next(request)
    finally:
        _request_id_ctx_var.reset(token)

    response.headers[REQUEST_ID_HEADER] = request_id
    return response
