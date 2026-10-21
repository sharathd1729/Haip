"""
Per-tenant + per-IP token-bucket rate limiting.

Default limits:
  Webhook endpoints:      300 req/min per IP  (fail-open on Redis outage)
  Auth endpoints:          10 req/min per IP  (fail-CLOSED on Redis outage)
  Authenticated routes:   600 req/min per tenant
  Unauthenticated routes:  60 req/min per IP
  Send endpoints:          30 req/min per tenant
  MCP endpoint:           120 req/min per PAT (fail-open on Redis outage)
  Public website forms:    10 req/min per IP for lead POSTs, 30/min for the rest of /api/v1/public/
                           (fail-open: platform_lead_service also counts per visitor in the database)

Implementation: Redis sliding-window counter (INCR + EXPIRE).
Returns 429 with Retry-After header when limit exceeded.
"""

import hashlib
import time
import json
from typing import Optional, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

log = structlog.get_logger()

# ─── Limit configuration ──────────────────────────────────────────────────────

# (requests, window_seconds)
_DEFAULT_AUTH   : Tuple[int, int] = (600, 60)   # 600/min per tenant
_DEFAULT_IP     : Tuple[int, int] = (60, 60)    # 60/min per IP (unauth)
_STRICT_AUTH    : Tuple[int, int] = (10, 60)    # 10/min per IP — login/register
_SEND_LIMIT     : Tuple[int, int] = (30, 60)    # 30/min per tenant — send endpoints
_WEBHOOK_LIMIT  : Tuple[int, int] = (300, 60)   # 300/min per IP — webhook endpoints
# D5: a leaked PAT had no throttle of its own -- it just fell through to the
# generic 60/min-per-IP unauthenticated tier (MCP requests never populate
# request.state.tenant_id, since that's set from a JWT, not a PAT). Keyed on
# the token itself, not IP, since one office NATs to one IP and would
# otherwise throttle every legitimate user there together.
_MCP_LIMIT      : Tuple[int, int] = (120, 60)   # 120/min per PAT

# Routes with tighter per-IP limits (fail-CLOSED: Redis outage blocks these)
_STRICT_PREFIXES = (
    "/oauth/token",
    "/oauth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/otp/send",
    "/api/v1/auth/otp/verify",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
)

# HAIP's own public website (no login): lead forms + the property assessment. Fail-OPEN on a Redis outage so a
# visitor's lead is not lost; the per-visitor hourly count in platform_lead_service holds without Redis.
_PUBLIC_SITE_PREFIX = "/api/v1/public/"
# Client websites built by HAIP (website builder): guest reads are page loads (high), writes are bookings and forms.
_CLIENT_SITE_PREFIXES = ("/api/v1/public/sites/", "/api/v1/public/preview/")
_CLIENT_SITE_READ_LIMIT: Tuple[int, int] = (240, 60)
_CLIENT_SITE_WRITE_LIMIT: Tuple[int, int] = (10, 60)
_CLIENT_SITE_VIEW_LIMIT: Tuple[int, int] = (120, 60)
_PUBLIC_LEAD_PATHS = ("/api/v1/public/leads",)
_PUBLIC_LEAD_LIMIT: Tuple[int, int] = (10, 60)    # 10/min per IP: lead POSTs
_PUBLIC_SITE_LIMIT: Tuple[int, int] = (30, 60)    # 30/min per IP: estimates, report reads

# Routes with tighter per-tenant send limits
_SEND_PREFIXES = (
    "/api/v1/conversations/",   # POST messages
    "/api/v1/messaging/",       # broadcasts
)

# Public API (API-key authenticated): per key, reads and sends counted separately.
_PUBLIC_API_PREFIX = "/api/public/v1"
_PUBLIC_READ_LIMIT: Tuple[int, int] = (300, 60)   # 300/min per API key
_PUBLIC_SEND_LIMIT: Tuple[int, int] = (60, 60)    # 60/min per API key for POST sends
_PUBLIC_DOC_PATHS = (_PUBLIC_API_PREFIX + "/docs", _PUBLIC_API_PREFIX + "/redoc", _PUBLIC_API_PREFIX + "/openapi.json")

# Routes to skip entirely (health checks, docs, and high-frequency polling)
_SKIP_PREFIXES = (
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/api/v1/users/me/heartbeat",
    "/api/v1/users/presence",
    "/api/v1/sse/",
)


def _get_redis():
    """Lazy Redis connection. Returns None if Redis unavailable."""
    try:
        import redis
        from app.core.config import settings
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception as e:
        log.error("rate_limit_redis_connect_failed", error=str(e))
        return None


def _check_limit(r, key: str, limit: int, window: int, strict: bool = False) -> Tuple[bool, int]:
    """
    Sliding-window counter. Returns (allowed, retry_after_seconds).

    strict=True: Redis errors return (False, 60) — fail-closed for auth endpoints.
    strict=False: Redis errors return (True, 0)  — fail-open for everything else.
    """
    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl == -1:
            r.expire(key, window)
            ttl = window
        if count == 1:
            r.expire(key, window)
        if count > limit:
            return False, max(ttl, 1)
        return True, 0
    except Exception as e:
        log.error("rate_limit_redis_error", key=key, error=str(e))
        if strict:
            return False, 60   # fail-closed: protect auth endpoints
        return True, 0         # fail-open: don't block normal traffic on Redis blip


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self._redis = None

    def _r(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip health checks and docs entirely
        for prefix in _SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Client IP
        forwarded = request.headers.get("X-Forwarded-For")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")

        r = self._r()

        # ── Webhook endpoints: separate looser per-IP limit ───────────────────
        if path.startswith("/api/v1/webhooks/"):
            if r is not None:
                limit, window = _WEBHOOK_LIMIT
                key = f"rl:ip:{ip}:webhook"
                allowed, retry_after = _check_limit(r, key, limit, window, strict=False)
                if not allowed:
                    log.warning("rate_limit_exceeded", path=path, ip=ip, key=key)
                    return _rate_limit_response(retry_after)
            return await call_next(request)

        # ── Public API: per-API-key limit (reads and sends counted separately) ─
        if path.startswith(_PUBLIC_API_PREFIX):
            if path.startswith(_PUBLIC_DOC_PATHS):
                return await call_next(request)
            if r is not None:
                auth_header = request.headers.get("authorization", "")
                raw_token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
                who = hashlib.sha256(raw_token.encode()).hexdigest()[:16] if raw_token else f"ip:{ip}"
                is_send = request.method == "POST"
                limit, window = _PUBLIC_SEND_LIMIT if is_send else _PUBLIC_READ_LIMIT
                key = f"rl:pubapi:{who}:{'send' if is_send else 'read'}"
                allowed, retry_after = _check_limit(r, key, limit, window, strict=False)
                if not allowed:
                    log.warning("rate_limit_exceeded", path=path, key=key)
                    return _public_rate_limit_response(retry_after)
            return await call_next(request)

        # ── MCP endpoint: per-PAT limit, not per-IP/tenant (D5) ───────────────
        # request.state.tenant_id is never set here -- MCP auth is a PAT in
        # the Authorization header, resolved inside mcp_endpoint itself, not
        # the JWT tenant_context_middleware reads. Hash the raw bearer value
        # directly rather than doing a DB lookup in middleware (keeps this
        # cheap, and throttles a bad/expired token attempt same as a valid
        # one -- both are "someone hammering this endpoint").
        if path.startswith("/mcp"):
            if r is not None:
                auth_header = request.headers.get("authorization", "")
                raw_token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
                if raw_token:
                    limit, window = _MCP_LIMIT
                    token_key = hashlib.sha256(raw_token.encode()).hexdigest()[:16]
                    key = f"rl:pat:{token_key}"
                    allowed, retry_after = _check_limit(r, key, limit, window, strict=False)
                    if not allowed:
                        log.warning("rate_limit_exceeded", path=path, key=key)
                        return _rate_limit_response(retry_after)
            return await call_next(request)

        # ── Client websites (website builder): per-IP, fail-open ──────────────
        if path.startswith(_CLIENT_SITE_PREFIXES):
            if r is not None:
                if request.method == "POST" and path.endswith("/views"):
                    tier, (limit, window) = "view", _CLIENT_SITE_VIEW_LIMIT
                elif request.method == "POST" and not path.endswith("/quote"):
                    tier, (limit, window) = "write", _CLIENT_SITE_WRITE_LIMIT
                else:
                    tier, (limit, window) = "read", _CLIENT_SITE_READ_LIMIT
                allowed, retry_after = _check_limit(r, f"rl:ip:{ip}:clientsite:{tier}", limit, window, strict=False)
                if not allowed:
                    log.warning("rate_limit_exceeded", path=path, tier=f"client_site_{tier}")
                    return _rate_limit_response(retry_after)
            return await call_next(request)

        # ── HAIP public website forms: per-IP, fail-open (DB backstop) ────────
        if path.startswith(_PUBLIC_SITE_PREFIX):
            if r is not None:
                is_lead = request.method == "POST" and path.startswith(_PUBLIC_LEAD_PATHS)
                limit, window = _PUBLIC_LEAD_LIMIT if is_lead else _PUBLIC_SITE_LIMIT
                key = f"rl:ip:{ip}:public:{'lead' if is_lead else 'site'}"
                allowed, retry_after = _check_limit(r, key, limit, window, strict=False)
                if not allowed:
                    log.warning("rate_limit_exceeded", path=path, tier="public_site")
                    return _rate_limit_response(retry_after)
            return await call_next(request)

        if r is None:
            # Redis unavailable — check if this is a strict path before allowing
            for prefix in _STRICT_PREFIXES:
                if path.startswith(prefix):
                    log.error("rate_limit_redis_unavailable_blocking_auth", path=path)
                    return _rate_limit_response(60)
            return await call_next(request)

        # Tenant ID from request state (set by tenant_context_middleware)
        tenant_id: Optional[str] = getattr(request.state, "tenant_id", None)

        # ── Strict IP limit (auth endpoints) — fail-CLOSED ───────────────────
        for prefix in _STRICT_PREFIXES:
            if path.startswith(prefix):
                limit, window = _STRICT_AUTH
                key = f"rl:ip:{ip}:{path}"
                allowed, retry_after = _check_limit(r, key, limit, window, strict=True)
                if not allowed:
                    log.warning("rate_limit_exceeded", path=path, ip=ip, key=key)
                    return _rate_limit_response(retry_after)
                return await call_next(request)

        # ── Per-tenant send limit ─────────────────────────────────────────────
        if tenant_id and request.method == "POST":
            for prefix in _SEND_PREFIXES:
                if path.startswith(prefix):
                    limit, window = _SEND_LIMIT
                    key = f"rl:tenant:{tenant_id}:send"
                    allowed, retry_after = _check_limit(r, key, limit, window)
                    if not allowed:
                        log.warning("rate_limit_exceeded", path=path, tenant_id=tenant_id, key=key)
                        return _rate_limit_response(retry_after)
                    break

        # ── Authenticated per-tenant limit ────────────────────────────────────
        if tenant_id:
            limit, window = _DEFAULT_AUTH
            key = f"rl:tenant:{tenant_id}:global"
            allowed, retry_after = _check_limit(r, key, limit, window)
            if not allowed:
                log.warning("rate_limit_exceeded", path=path, tenant_id=tenant_id, key=key)
                return _rate_limit_response(retry_after)
        else:
            # ── Unauthenticated per-IP limit ──────────────────────────────────
            limit, window = _DEFAULT_IP
            key = f"rl:ip:{ip}:unauth"
            allowed, retry_after = _check_limit(r, key, limit, window)
            if not allowed:
                log.warning("rate_limit_exceeded", path=path, ip=ip, key=key)
                return _rate_limit_response(retry_after)

        return await call_next(request)


def _rate_limit_response(retry_after: int) -> Response:
    body = json.dumps({
        "detail": "Rate limit exceeded. Please slow down.",
        "retry_after": retry_after,
    })
    return Response(
        content=body,
        status_code=429,
        headers={
            "Content-Type": "application/json",
            "Retry-After": str(retry_after),
            "X-RateLimit-Reset": str(int(time.time()) + retry_after),
        },
    )


def _public_rate_limit_response(retry_after: int) -> Response:
    """Same {"error": {...}} shape as every other public API error."""
    body = json.dumps({"error": {"code": "rate_limited", "message": f"Too many requests. Retry in {retry_after} seconds."}})
    return Response(
        content=body, status_code=429,
        headers={"Content-Type": "application/json", "Retry-After": str(retry_after),
                 "X-RateLimit-Reset": str(int(time.time()) + retry_after)},
    )
