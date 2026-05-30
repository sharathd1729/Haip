"""
run_insights — Celery task that runs all AI insight detectors for every tenant.

Beat schedules:
  - run-insights-every-15min   : every 15 minutes (covers A1, A2, D3)
  - run-insights-hourly        : every hour at :05 (covers B, C detectors)
"""

import logging
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.services.insight_detector import run_all_detectors

log = logging.getLogger(__name__)


@shared_task(name="app.workers.tasks.run_insights.run_for_tenant", bind=True, max_retries=2)
def run_for_tenant(self, tenant_id: str):
    """Run all insight detectors for a single tenant."""
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        count = run_all_detectors(db, tenant_id)
        log.info("Insights: %d active for tenant %s", count, tenant_id)
        return {"tenant_id": tenant_id, "active_insights": count}
    except Exception as exc:
        log.error("run_for_tenant failed for %s: %s", tenant_id, exc)
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@shared_task(name="app.workers.tasks.run_insights.run_all_tenants")
def run_all_tenants():
    """Fan out: enqueue a run_for_tenant task for every active tenant."""
    db: Session = SessionLocal()
    try:
        tenant_ids = [
            str(t.id)
            for t in db.query(Tenant).filter(Tenant.is_active == True).all()
        ]
    finally:
        db.close()

    for tid in tenant_ids:
        run_for_tenant.delay(tid)

    log.info("Insights: queued %d tenants", len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
