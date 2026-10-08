"""Send queued webhook deliveries and retry the ones that failed.

deliver_webhook is queued right after the transaction that created the delivery commits.
retry_due runs every minute and sends anything that is due (a retry whose backoff has
elapsed, or a delivery whose first dispatch was lost because the broker was down).
"""
from datetime import datetime, timedelta, timezone

import structlog
from celery.exceptions import MaxRetriesExceededError

from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()

_BATCH = 200
_KEEP_DAYS = 30


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="webhooks.deliver")
def deliver_webhook(self, delivery_id: str, tenant_id: str):
    from app.services import webhook_service
    db = SessionLocal()
    try:
        webhook_service.deliver(db, delivery_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 -- infrastructure trouble (DB), not a customer-side failure
        db.rollback()
        log.error("webhook_deliver_error", delivery_id=delivery_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("webhook_deliver_retries_exhausted", delivery_id=delivery_id)
    finally:
        db.close()


@celery_app.task(name="webhooks.retry_due")
def retry_due():
    """Fan out due deliveries, one tenant at a time (the tables are under RLS)."""
    from app.models.tenant import Tenant
    from app.models.webhook import WebhookDelivery
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        queued = 0
        for (tenant_id,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all():
            set_tenant_context(db, tenant_id)
            due = (db.query(WebhookDelivery.id)
                   .filter(WebhookDelivery.tenant_id == tenant_id, WebhookDelivery.status == "pending",
                           WebhookDelivery.next_attempt_at <= now)
                   .order_by(WebhookDelivery.next_attempt_at).limit(_BATCH).all())
            for (delivery_id,) in due:
                deliver_webhook.apply_async(kwargs={"delivery_id": delivery_id, "tenant_id": tenant_id}, queue="call_ingest")
                queued += 1
        if queued:
            log.info("webhook_retry_fanned_out", count=queued)
    finally:
        db.close()


@celery_app.task(name="webhooks.purge_old")
def purge_old():
    """Keep the delivery log to 30 days."""
    from app.models.tenant import Tenant
    from app.models.webhook import WebhookDelivery
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_KEEP_DAYS)
        for (tenant_id,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all():
            set_tenant_context(db, tenant_id)
            db.query(WebhookDelivery).filter(WebhookDelivery.tenant_id == tenant_id, WebhookDelivery.created_at < cutoff,
                                             WebhookDelivery.status != "pending").delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()
