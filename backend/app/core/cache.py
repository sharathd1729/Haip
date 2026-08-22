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


def incr(key: str, ttl: int = 86400) -> Optional[int]:
    """Atomically increment a counter, returning the new value -- or None if
    Redis is unreachable. Callers must handle None (fail-open on their own
    terms, e.g. round-robin rotation degrading to always-first rather than
    raising). TTL is refreshed on every call so a low-traffic counter never
    needs a separate reset step."""
    r = _client()
    if r is None:
        return None
    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        value, _ = pipe.execute()
        return value
    except Exception as exc:
        log.debug("Cache INCR failed for %s: %s", key, exc)
        return None


def idem_check_and_set(key: str, ttl: int = 86400) -> bool:
    """Atomic idempotency check for MCP write tools (HAIP_MCP_Connector_Plan.md
    ticket 3.6). Returns True the first time a key is seen (caller should
    proceed), False if it's been seen before within `ttl` seconds (caller
    should treat the call as a duplicate and skip re-executing the write).
    Fails open -- returns True (proceed) -- if Redis is unavailable, same
    as this module's other non-critical-path Redis usage; a missed dedup
    on a Redis blip is preferable to blocking every write tool call."""
    r = _client()
    if r is None:
        return True
    try:
        return bool(r.set(key, "1", nx=True, ex=ttl))
    except Exception as exc:
        log.debug("Idempotency check failed for %s: %s", key, exc)
        return True


def invalidate_tenant(tenant_id: str) -> None:
    """Delete all analytics + capability cache keys for a tenant (call on
    data-changing events). Capability keys included so authz_service edits
    (role_capabilities matrix changes) have one invalidation path to call,
    not a parallel one -- see HAIP_MCP_Connector_Plan.md ticket 1.4."""
    r = _client()
    if r is None:
        return
    try:
        for pattern in (f"haip:analytics:*:{tenant_id}:*", f"cap:{tenant_id}:*"):
            keys = list(r.scan_iter(pattern, count=100))
            if keys:
                r.delete(*keys)
    except Exception as exc:
        log.debug("Cache invalidation failed for tenant %s: %s", tenant_id, exc)


# ── L1-L4 Workspace Cache Layer ───────────────────────────────────────────────
# Per Scale + Migrate architecture: O(1) lookup via Redis, fallback to DB.

def _rget(key: str):
    r = _client()
    if not r:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _rset(key: str, value, ttl: int) -> None:
    r = _client()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def _rdel(*keys: str) -> None:
    r = _client()
    if not r:
        return
    try:
        r.delete(*keys)
    except Exception:
        pass


def _rdel_pattern(pattern: str) -> None:
    r = _client()
    if not r:
        return
    try:
        keys = list(r.scan_iter(pattern, count=200))
        if keys:
            r.delete(*keys)
    except Exception:
        pass


# L1 — Workspace Context (active_modules + flags), TTL 5 min
def ctx_get(workspace_id: str):
    return _rget(f"workspace_ctx:{workspace_id}")


def ctx_set(workspace_id: str, data: dict) -> None:
    _rset(f"workspace_ctx:{workspace_id}", data, 300)


def ctx_bust(workspace_id: str) -> None:
    _rdel(f"workspace_ctx:{workspace_id}", f"feature_flags:{workspace_id}")


# L2 — Feature Flags, TTL 60 min
def flags_get(workspace_id: str):
    return _rget(f"feature_flags:{workspace_id}")


def flags_set(workspace_id: str, flags: dict) -> None:
    _rset(f"feature_flags:{workspace_id}", flags, 3600)


# L3 — Metric Results, TTL from registry (default 15 min)
def metric_get(workspace_id: str, metric_key: str, range_key: str):
    return _rget(f"metric_results:{workspace_id}:{metric_key}:{range_key}")


def metric_set(workspace_id: str, metric_key: str, range_key: str, value, ttl: int = 900) -> None:
    _rset(f"metric_results:{workspace_id}:{metric_key}:{range_key}", value, ttl)


def metric_bust(workspace_id: str, metric_key: str | None = None) -> None:
    pattern = (
        f"metric_results:{workspace_id}:{metric_key}:*"
        if metric_key
        else f"metric_results:{workspace_id}:*"
    )
    _rdel_pattern(pattern)


# L4 — Dashboard Snapshot, TTL 5 min, bust on dashboard save
def snap_get(dashboard_id: str):
    return _rget(f"dashboard_snap:{dashboard_id}")


def snap_set(dashboard_id: str, data: dict) -> None:
    _rset(f"dashboard_snap:{dashboard_id}", data, 300)


def snap_bust(dashboard_id: str) -> None:
    _rdel(f"dashboard_snap:{dashboard_id}")


# ── SSE pub/sub ───────────────────────────────────────────────────────────────

def publish_workspace_event(workspace_id: str, event_type: str, payload: dict) -> None:
    """
    Publish to workspace-scoped SSE channel.
    Events: metric_update | module_changed | goal_alert | insight_new
    SSE endpoint subscribes to ws_events:{workspace_id} channel.
    """
    r = _client()
    if not r:
        return
    try:
        import json as _json
        msg = _json.dumps(
            {"event": event_type, "workspace_id": workspace_id, **payload},
            default=str,
        )
        r.publish(f"ws_events:{workspace_id}", msg)
    except Exception as exc:
        log.debug("SSE publish failed: %s", exc)
