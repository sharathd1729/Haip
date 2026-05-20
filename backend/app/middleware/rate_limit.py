"""
B8 — Per-tenant + per-IP token-bucket rate limiting.

Default limits:
  Authenticated routes:  600 req/min per tenant
  Unauthenticated routes: 60 req/min per IP
  Auth endpoints (/auth/login, /auth/register): 10 req/min per IP
  Send endpoints (/messages, /otp): 30 req/min per tenant

Implementation: Redis sliding-window counter (INCR + EXPIRE).
Returns 429 with Retry-After header when limit exceeded.
"""

import time
import json
from typing import Optional, Dict, Tuple
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

# Routes with tighter per-IP limits
_STRICT_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/otp/send",
    "/api/v1/auth/otp/verify",
    "/api/v1/auth/password/reset",
)

# Routes with tighter per-tenant send limits
_SEND_PREFIXES = (
    "/api/v1/conversations/",   # POST messages
    "/api/v1/messaging/",       # broadcasts
)

# Routes to skip entirely (webhooks use their own shared-secret auth)
_SKIP_PREFIXES = (
    "/api/v1/webhooks/",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
)


def _get_redis():
    """Lazy Redis connection. Returns None if Redis unavailable (fail-open)."""
    try:
        import redis
        from app.core.config import settings
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _check_limit(r, key: str, limit: int, window: int) -> Tuple[bool, int]:
    """
    Sliding-window counter. Returns (allowed, retry_after_seconds).
    Uses Redis INCR + EXPIRE atomically via pipeline.
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
    except Exception:
        return True, 0   # fail-open: Redis error → allow request


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

        # Skip rate-limited paths
        for prefix in _SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        r = self._r()
        if r is None:
            # Redis unavailable — fail-open
            return await call_next(request)

        # Client IP
        forwarded = request.headers.get("X-Forwarded-For")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")

        # Tenant ID from request state (set by tenant_context_middleware)
        tenant_id: Optional[str] = getattr(request.state, "tenant_id", None)

        # ── Strict IP limit (auth endpoints) ─────────────────────────────────
        for prefix in _STRICT_PREFIXES:
            if path.startswith(prefix):
                limit, window = _STRICT_AUTH
                key = f"rl:ip:{ip}:{path}"
                allowed, retry_after = _check_limit(r, key, limit, window)
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
                    break   # only apply one rule

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
