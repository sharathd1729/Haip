"""Nightly pull of Meta ad insights for every workspace that has chosen an ad account.

Re-reads the last 7 days each run because Meta restates recent figures. A rate limit or an outage is
logged and left for the next night; a rejected token marks the integration as errored so the Dashboard bar
and the owner see it.
"""
import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.integration import Integration
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="meta_ads.sync_tenant")
def sync_tenant(tenant_id: str, days: int = 7):
    from app.adapters.marketing.meta_ads import MetaAdsError
    from app.services import meta_ads_service

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        if not db.query(Tenant).filter_by(id=tenant_id).first():
            return {"tenant_id": tenant_id, "status": "no_tenant"}
        try:
            result = meta_ads_service.sync(db, tenant_id, days=days)
        except meta_ads_service.NotConfigured as exc:
            return {"tenant_id": tenant_id, "status": "skipped", "reason": str(exc)}
        except MetaAdsError as exc:
            return {"tenant_id": tenant_id, "status": "rate_limited" if exc.rate_limited else "failed", "error": str(exc)[:200]}
        return {"tenant_id": tenant_id, "status": "ok", **result}
    finally:
        db.close()


@shared_task(name="meta_ads.backfill_tenant")
def backfill_tenant(tenant_id: str, months: int = 12):
    """Load up to `months` of ad history for one workspace, a month at a time. Progress lives on the integration."""
    from app.adapters.marketing.meta_ads import MetaAdsError
    from app.services import meta_ads_service

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        try:
            state = meta_ads_service.backfill(db, tenant_id, months=months)
        except meta_ads_service.NotConfigured as exc:
            return {"tenant_id": tenant_id, "status": "skipped", "reason": str(exc)}
        except MetaAdsError as exc:
            return {"tenant_id": tenant_id, "status": "failed", "error": str(exc)[:200]}
        except Exception as exc:
            # Leave a visible trace on the integration instead of a "running" state that never ends.
            db.rollback()
            row = meta_ads_service.get_row(db, tenant_id)
            if row:
                meta_ads_service._mark(db, row, backfill={**((row.config or {}).get("backfill") or {}),
                                                         "state": "stopped", "stopped_because": "error"})
            log.error("meta_ads_backfill_crashed", tenant_id=tenant_id, error=str(exc)[:200])
            raise
        return {"tenant_id": tenant_id, "status": state["state"], "rows": state["rows"], "failed": len(state["failed"])}
    finally:
        db.close()


@shared_task(name="meta_ads.sync_all_tenants")
def sync_all_tenants():
    """Fan out: one sync per workspace that has a meta_ads integration."""
    db = SessionLocal()
    try:
        tenant_ids = [i.tenant_id for i in db.query(Integration).filter(Integration.kind == "meta_ads").all()]
    finally:
        db.close()
    for tid in tenant_ids:
        sync_tenant.apply_async(kwargs={"tenant_id": tid}, queue="whatsapp")
    log.info("meta_ads_sync_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
