"""Celery task: generate the Today (Worklist) AI Daily Briefing.

Called:
  - Every 30 min via beat schedule (tenant_id="__all__")
  - On-demand from GET /worklist/briefing on a cache miss (single tenant,
    non-blocking -- the request itself never waits on the LLM call)
"""
import structlog
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.daily_briefing_service import generate_briefing

log = structlog.get_logger()


@shared_task(name="tasks.daily_briefing.generate", bind=True, max_retries=2, default_retry_delay=60)
def generate_daily_briefing(self, tenant_id: str):
    """Generate (and cache) the briefing for one tenant or every active tenant.

    tenant_id="__all__" → iterate every active tenant.
    """
    db: Session = SessionLocal()
    try:
        if tenant_id == "__all__":
            tenants = db.query(Tenant).filter(Tenant.is_active.is_(True)).all()
        else:
            tenants = db.query(Tenant).filter(Tenant.id == tenant_id).all()

        for tenant in tenants:
            try:
                generate_briefing(db, tenant.id)
            except Exception as exc:  # noqa: BLE001 -- one tenant's failure must not skip the rest
                log.warning("daily_briefing_tenant_failed", tenant=tenant.id, error=str(exc))

    except Exception as exc:
        log.error("generate_daily_briefing_task_failed", error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
