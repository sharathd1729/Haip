"""
A6 — Incremental lost-reason clustering.

Nightly incremental run: cluster only inquiries closed since last run.
Quarterly full re-fit (FULL_REFIT_DAYS cadence).

Cluster state is stored per-tenant in tenant.brand_config["cluster_state"]:
  {
    "last_run_at": "ISO datetime",
    "full_refit_at": "ISO datetime",
    "themes": [ {reason, count, percentage, example_notes}, ... ]
  }
"""

import json
from datetime import datetime, timedelta, timezone
from app.workers.celery_app import celery_app
from app.workers.retry_policy import task_with_retry
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.lost_reason_service import get_lost_inquiries, cluster_themes
import structlog

log = structlog.get_logger()

FULL_REFIT_DAYS = 90   # run a full re-fit every 90 days


@celery_app.task(**task_with_retry("lost_reason_cluster.nightly", max_retries=2))
def lost_reason_cluster_nightly(self):
    """
    A6: Nightly incremental run across all active tenants.
    Only processes inquiries closed since last_run_at.
    """
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).filter_by(is_active=True).all()
        now = datetime.now(timezone.utc)
        for tenant in tenants:
            try:
                _process_tenant_incremental(db, tenant, now, force_full=False)
            except Exception as exc:
                log.error("cluster_tenant_error", tenant_id=tenant.id, error=str(exc))
    finally:
        db.close()


@celery_app.task(**task_with_retry("lost_reason_cluster.full_refit", max_retries=1))
def lost_reason_cluster_full(self, tenant_id: str):
    """A6: Full re-fit for a single tenant. Triggered quarterly."""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant:
            _process_tenant_incremental(db, tenant, datetime.now(timezone.utc), force_full=True)
    finally:
        db.close()


def _process_tenant_incremental(db, tenant: Tenant, now: datetime, force_full: bool = False):
    config = tenant.brand_config or {}
    cluster_state = config.get("cluster_state") or {}

    last_run_str = cluster_state.get("last_run_at")
    full_refit_str = cluster_state.get("full_refit_at")

    # Determine whether this is a full re-fit
    if force_full:
        is_full = True
    elif not full_refit_str:
        is_full = True  # first ever run
    else:
        last_full = datetime.fromisoformat(full_refit_str)
        is_full = (now - last_full).days >= FULL_REFIT_DAYS

    if is_full:
        # Full re-fit: scan all lost inquiries in last 365 days
        lost = get_lost_inquiries(db, tenant.id, days=365)
        full_refit_at = now.isoformat()
    else:
        # Incremental: only inquiries closed since last run
        if last_run_str:
            since_dt = datetime.fromisoformat(last_run_str)
            days_since = max(1, (now - since_dt).days + 1)
        else:
            days_since = 7
        lost = get_lost_inquiries(db, tenant.id, days=days_since)
        full_refit_at = full_refit_str or now.isoformat()

    if len(lost) < 2:
        log.info("cluster_skipped_insufficient_data", tenant_id=tenant.id, count=len(lost))
        return

    # If incremental, merge with existing theme counts
    if not is_full and cluster_state.get("themes"):
        lost = _merge_with_existing(lost, cluster_state["themes"], db, tenant.id)

    themes = cluster_themes(lost)

    # Update cluster state
    cluster_state["last_run_at"] = now.isoformat()
    cluster_state["full_refit_at"] = full_refit_at
    cluster_state["themes"] = themes
    config["cluster_state"] = cluster_state
    config["lost_reason_themes"] = themes   # keep legacy key for dashboard
    tenant.brand_config = config
    db.commit()

    log.info(
        "cluster_done",
        tenant_id=tenant.id,
        themes=len(themes),
        lost_count=len(lost),
        is_full=is_full,
    )


def _merge_with_existing(new_lost: list, existing_themes: list, db, tenant_id: str) -> list:
    """
    Merge newly-closed inquiries with existing cluster data.
    Returns a combined list for re-clustering.
    The 'existing_themes' provides synthetic entries so centroid mass is preserved.
    """
    merged = list(new_lost)
    for theme in existing_themes:
        # Re-add synthetic entries representing existing cluster mass
        count = theme.get("count", 0)
        reason = theme.get("reason", "")
        if reason and count > 0:
            merged.extend([{"id": f"synthetic_{i}", "reason": reason, "note": None}
                           for i in range(min(count, 50))])  # cap at 50 to avoid explosion
    return merged
