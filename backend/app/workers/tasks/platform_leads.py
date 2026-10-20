"""HAIP's own website leads (platform_lead_service).

  platform_leads.notify   push + email the sales workspace's owners about one new lead (once per lead)
"""
import structlog
from celery.exceptions import MaxRetriesExceededError

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="platform_leads.notify")
def notify_owners(self, lead_id: str):
    from app.core.database import set_tenant_context
    from app.models.platform_lead import PlatformLead
    from app.services import platform_lead_service

    db = SessionLocal()
    try:
        lead = db.query(PlatformLead).filter_by(id=lead_id).first()
        if lead is not None and lead.workspace_tenant_id:
            set_tenant_context(db, lead.workspace_tenant_id)   # owners + push subscriptions are tenant rows
        return platform_lead_service.notify(db, lead_id)
    except Exception as exc:  # noqa: BLE001 -- DB blip; notify() is a no-op once notified_at is set
        db.rollback()
        log.error("platform_lead_notify_failed", lead_id=lead_id, error=type(exc).__name__)
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("platform_lead_notify_gave_up", lead_id=lead_id)
    finally:
        db.close()
