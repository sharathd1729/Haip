"""Meta lead-form leads: read each workspace's forms every few minutes, plus an owner-started import of older leads."""

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.integration import Integration

log = structlog.get_logger()


@shared_task(name="meta_lead_forms.sync_tenant")
def sync_tenant(tenant_id: str, since_days: int | None = None):
    from app.adapters.marketing.meta_ads import MetaAdsError
    from app.services import meta_lead_forms_service as svc

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        try:
            return {"tenant_id": tenant_id, "status": "ok", **svc.sync(db, tenant_id, since_days=since_days)}
        except svc.NotEnabled as exc:
            return {"tenant_id": tenant_id, "status": "skipped", "reason": str(exc)}
        except MetaAdsError as exc:
            return {
                "tenant_id": tenant_id,
                "status": "rate_limited" if exc.rate_limited else "failed",
                "error": str(exc)[:200],
            }
    finally:
        db.close()


@shared_task(name="meta_lead_forms.sync_all_tenants")
def sync_all_tenants():
    """Fan out: one read per workspace whose Meta Business connection has lead forms switched on."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Integration.tenant_id, Integration.config)
            .filter(Integration.kind == "meta_business", Integration.status == "active")
            .all()
        )
        queued = 0
        for tenant_id, config in rows:
            if ((config or {}).get("lead_forms") or {}).get("enabled"):
                sync_tenant.apply_async(kwargs={"tenant_id": tenant_id}, queue="whatsapp")
                queued += 1
        return {"queued": queued}
    finally:
        db.close()
