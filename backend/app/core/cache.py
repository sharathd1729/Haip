"""
Thin Redis cache helper for analytics endpoints.

Usage:
    from app.core.cache import get_cached, set_cached, cache_key

    key = cache_key("executive", tenant_id, range_days=30, property_ids="all")
    cached = get_cached(key)
    if cached is not None:
        return cached

    result = _compute_expensive_query(...)
    set_cached(key, result, ttl=300)
    return result

Falls back to None silently when Redis is unavailable (e.g. local dev without Redis).
"""

import json
import hashlib
import logging
from typing import Any, Optional

import redis
from app.core.config import settings

log = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None


def _client() -> Optional[redis.Redis]:
    """Lazily connect; return None if Redis is unreachable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import ssl
        url = settings.REDIS_URL
        ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE} if url.startswith("rediss://") else {}
        r = redis.from_url(url, decode_responses=True, socket_connect_timeout=1, **ssl_opts)
        r.ping()
        _redis_client = r
        return _redis_client
    except Exception as exc:
        log.debug("Redis unavailable — analytics cache disabled: %s", exc)
        return None


def cache_key(namespace: str, tenant_id: str, **params) -> str:
    """Build a deterministic cache key from namespace + tenant + query params."""
    param_str = json.dumps(params, sort_keys=True)
    digest = hashlib.sha256(param_str.encode()).hexdigest()[:12]
    return f"haip:analytics:{namespace}:{tenant_id}:{digest}"


def get_cached(key: str) -> Optional[Any]:
    """Return deserialized value or None on cache miss / Redis down."""
    r = _client()
    if r is None:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        log.debug("Cache GET failed for %s: %s", key, exc)
        return None


def set_cached(key: str, value: Any, ttl: int = 300) -> None:
    """Serialize and store value; silently ignore Redis errors."""
    r = _client()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        log.debug("Cache SET failed for %s: %s", key, exc)


def invalidate_tenant(tenant_id: str) -> None:
    """Delete all analytics cache keys for a tenant (call on data-changing events)."""
    r = _client()
    if r is None:
        return
    try:
        pattern = f"haip:analytics:*:{tenant_id}:*"
        keys = list(r.scan_iter(pattern, count=100))
        if keys:
            r.delete(*keys)
    except Exception as exc:
        log.debug("Cache invalidation failed for tenant %s: %s", tenant_id, exc)
