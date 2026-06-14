"""
invalidate_cache — event-driven cache invalidation for workspace-level Redis keys.

Called directly (not via beat schedule) when:
- A workspace module is activated/deactivated → invalidate WorkspaceCtx
- A feature flag changes → invalidate FeatureFlags + WorkspaceCtx
- A metric snapshot is written → invalidate MetricResults
- A dashboard is saved → invalidate DashboardSnap

Key naming conventions (must match deps.py cache reads):
  workspace_ctx:{workspace_id}      TTL 300s
  feature_flags:{workspace_id}      TTL 3600s
  metric_results:{workspace_id}:*   TTL from registry
  dashboard_snap:{dashboard_id}     TTL 300s
  widget_render:{workspace_id}:*    TTL variable
"""

from __future__ import annotations

import structlog
from celery import shared_task

log = structlog.get_logger()


def _get_redis():
    from app.core.config import settings
    import redis
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@shared_task(name="app.workers.tasks.invalidate_cache.workspace_context", bind=True)
def workspace_context(self, workspace_id: str):
    """Invalidate WorkspaceCtx and FeatureFlags cache for one workspace."""
    r = _get_redis()
    keys = [
        f"workspace_ctx:{workspace_id}",
        f"feature_flags:{workspace_id}",
    ]
    deleted = r.delete(*keys)
    log.info("cache_invalidated_workspace_ctx",
             workspace_id=workspace_id, keys_deleted=deleted)
    return {"workspace_id": workspace_id, "keys_deleted": deleted}


@shared_task(name="app.workers.tasks.invalidate_cache.metric_results", bind=True)
def metric_results(self, workspace_id: str, metric_key: str | None = None):
    """Invalidate metric result cache. If metric_key=None, clears all metrics for workspace."""
    r = _get_redis()
    if metric_key:
        pattern = f"metric_results:{workspace_id}:{metric_key}:*"
    else:
        pattern = f"metric_results:{workspace_id}:*"
    keys = list(r.scan_iter(pattern, count=100))
    deleted = r.delete(*keys) if keys else 0
    log.info("cache_invalidated_metric_results",
             workspace_id=workspace_id, metric_key=metric_key, keys_deleted=deleted)
    return {"workspace_id": workspace_id, "keys_deleted": deleted}


@shared_task(name="app.workers.tasks.invalidate_cache.dashboard_snap", bind=True)
def dashboard_snap(self, dashboard_id: str):
    """Invalidate snapshot cache for one dashboard."""
    r = _get_redis()
    key = f"dashboard_snap:{dashboard_id}"
    deleted = r.delete(key)
    log.info("cache_invalidated_dashboard_snap",
             dashboard_id=dashboard_id, deleted=deleted)
    return {"dashboard_id": dashboard_id, "deleted": deleted}


@shared_task(name="app.workers.tasks.invalidate_cache.widget_render", bind=True)
def widget_render(self, workspace_id: str, widget_key: str | None = None):
    """Invalidate widget render cache for one workspace (optionally one widget type)."""
    r = _get_redis()
    if widget_key:
        pattern = f"widget_render:{workspace_id}:{widget_key}:*"
    else:
        pattern = f"widget_render:{workspace_id}:*"
    keys = list(r.scan_iter(pattern, count=100))
    deleted = r.delete(*keys) if keys else 0
    log.info("cache_invalidated_widget_render",
             workspace_id=workspace_id, widget_key=widget_key, keys_deleted=deleted)
    return {"workspace_id": workspace_id, "keys_deleted": deleted}


@shared_task(name="app.workers.tasks.invalidate_cache.full_workspace", bind=True)
def full_workspace(self, workspace_id: str):
    """Nuclear option: clear all cache keys for a workspace."""
    r = _get_redis()
    patterns = [
        f"workspace_ctx:{workspace_id}",
        f"feature_flags:{workspace_id}",
        f"metric_results:{workspace_id}:*",
        f"widget_render:{workspace_id}:*",
    ]
    total = 0
    for pattern in patterns:
        if "*" in pattern:
            keys = list(r.scan_iter(pattern, count=200))
            if keys:
                total += r.delete(*keys)
        else:
            total += r.delete(pattern)
    log.info("cache_invalidated_full_workspace",
             workspace_id=workspace_id, keys_deleted=total)
    return {"workspace_id": workspace_id, "keys_deleted": total}
