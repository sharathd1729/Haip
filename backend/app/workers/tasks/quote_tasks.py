"""Sent quotes (queue ``whatsapp``, exact-name routes in celery_app.py).

  quotes.send_with_links        render the quote PDF and send ratha_quote_payment_v1 (+ the fallback link while the
                                24-hour window is open). Queued by POST /quotes/{id}/send; safe to retry (stored PDF
                                reused, WhatsApp send idempotent per quote group + link).
  quotes.cancel_payment_links   cancel the other option's Razorpay link once a quote became a booking.
"""
import structlog
from celery.exceptions import MaxRetriesExceededError

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=4, default_retry_delay=60, name="quotes.send_with_links")
def send_with_links(self, tenant_id: str, quote_id: str, link_id: str):
    from app.core.database import set_tenant_context
    from app.services import quote_send_service
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return quote_send_service.deliver(db, tenant_id, quote_id, link_id)
    except Exception as exc:  # noqa: BLE001 -- storage/DB blip: every step is safe to repeat
        db.rollback()
        log.error("quote_send_failed", tenant_id=tenant_id, quote_id=quote_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("quote_send_gave_up", tenant_id=tenant_id, quote_id=quote_id)
            quote_send_service.gave_up(db, tenant_id, quote_id, f"could not render or send the quote: {exc}")
    finally:
        db.close()


@celery_app.task(name="quotes.cancel_payment_links")
def cancel_payment_links(tenant_id: str, link_ids: list):
    from app.core.database import set_tenant_context
    from app.services import quote_payment_service
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return quote_payment_service.cancel_links(db, tenant_id, list(link_ids or []))
    finally:
        db.close()
