"""The AI sales agent's own send (queue ``whatsapp``, exact-name route in celery_app.py).

  sales_agent.send_quote   autopilot: send the prepared quote + payment link through quote_send_service.send_as_agent (the
                           same checks, links and WhatsApp message as a person's send). Queued by sales_agent_service after the
                           concierge reply itself went out; the action was already moved pending -> sending by one guarded
                           UPDATE, so a retry or a second worker finds it no longer "sending" once it is done.
"""
import structlog
from celery.exceptions import MaxRetriesExceededError

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60, name="sales_agent.send_quote")
def send_quote(self, tenant_id: str, action_id: str):
    from app.core.database import set_tenant_context
    from app.services import sales_action_service
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return sales_action_service.deliver_autopilot(db, tenant_id, action_id)
    except Exception as exc:  # noqa: BLE001 -- a DB/broker blip: links are reused and the message is idempotent per quote + link
        db.rollback()
        log.error("sales_agent_send_task_failed", tenant_id=tenant_id, action_id=action_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            row = db.query(sales_action_service.SalesAction).filter_by(id=action_id, tenant_id=tenant_id).first()
            if row is not None and row.status == "sending":
                sales_action_service._agent_failed(db, row, f"The agent could not send the quote: {type(exc).__name__}")
    finally:
        db.close()
