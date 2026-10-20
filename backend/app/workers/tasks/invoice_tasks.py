"""Invoices and booking payment follow-ups (queue ``whatsapp``, exact-name routes in celery_app.py).

  invoices.after_payment     a booking payment landed: invoice/receipt + PDF + WhatsApp + staff push
  invoices.render_pdf        (re)render one issued document's PDF, e.g. after "Reissue invoice"
  invoices.send_booking_confirmation  the new-booking flow's confirmation: render the invoice PDF, then send it
  payments.notify_staff      push a payment alert (used by the quote-link path, which has no booking yet)
  payments.balance_reminders beat, daily 09:35 IST: balance due in 3 days -> link + ratha_balance_due_v1 (opt-in)
"""
from datetime import datetime

import structlog
from celery.exceptions import MaxRetriesExceededError

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=4, default_retry_delay=60, name="invoices.after_payment")
def after_payment(self, tenant_id: str, payment_id: str):
    from app.core.database import set_tenant_context
    from app.services import payment_followup_service
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return payment_followup_service.after_payment(db, tenant_id, payment_id)
    except Exception as exc:  # noqa: BLE001 -- storage/DB blip: every step is safe to repeat
        log.error("invoice_after_payment_failed", tenant_id=tenant_id, payment_id=payment_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("invoice_after_payment_gave_up", tenant_id=tenant_id, payment_id=payment_id)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=4, default_retry_delay=60, name="invoices.render_pdf")
def render_pdf(self, tenant_id: str, invoice_id: str):
    from app.core.database import set_tenant_context
    from app.services import payment_followup_service
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return payment_followup_service.render_invoice(db, tenant_id, invoice_id)
    except Exception as exc:  # noqa: BLE001
        log.error("invoice_render_failed", tenant_id=tenant_id, invoice_id=invoice_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("invoice_render_gave_up", tenant_id=tenant_id, invoice_id=invoice_id)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=4, default_retry_delay=60, name="invoices.send_booking_confirmation")
def send_booking_confirmation(self, tenant_id: str, stay_id: str, invoice_id=None, text: str = "", channel: str = "template"):
    from app.core.database import set_tenant_context
    from app.services import booking_compose_send
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return booking_compose_send.deliver_confirmation(db, tenant_id, stay_id, invoice_id, text, channel)
    except Exception as exc:  # noqa: BLE001 -- storage/DB blip: the render and the send are safe to repeat
        log.error("booking_confirmation_failed", tenant_id=tenant_id, stay_id=stay_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("booking_confirmation_gave_up", tenant_id=tenant_id, stay_id=stay_id)
    finally:
        db.close()


@celery_app.task(name="payments.notify_staff")
def notify_staff(tenant_id: str, title: str, body: str, url: str = "/dashboard/my-day"):
    from app.core.database import set_tenant_context
    from app.services.payment_followup_service import notify
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        notify(db, tenant_id, title, body, url)
    finally:
        db.close()


@celery_app.task(name="payments.balance_reminders")
def balance_reminders():
    """One pass over every active tenant. A tenant's failure is logged and does not stop the others."""
    from zoneinfo import ZoneInfo

    from app.core.database import set_tenant_context
    from app.models.tenant import Tenant
    from app.services import balance_reminder_service

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    db = SessionLocal()
    results = {}
    try:
        tenants = [(t.id, bool(((t.brand_config or {}).get("payments") or {}).get("auto_balance_reminder")))
                   for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
        for tenant_id, enabled in tenants:
            if not enabled:
                continue
            try:
                set_tenant_context(db, tenant_id)
                tenant = db.query(Tenant).filter_by(id=tenant_id).first()
                results[tenant_id] = balance_reminder_service.run_for_tenant(db, tenant, today)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                log.error("balance_reminders_tenant_failed", tenant_id=tenant_id, error=str(exc))
        return results
    finally:
        db.close()
