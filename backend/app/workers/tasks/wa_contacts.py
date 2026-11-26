"""Bulk drip enrolment from the WhatsApp contacts page: one batch of guests per task, spaced a minute apart by
services/wa_contacts.queue_enrolment. Routed by the "whatsapp.*" rule to the whatsapp queue."""
import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="whatsapp.contacts_enrol_flow")
def enrol_flow_batch(tenant_id: str, flow_id: str, guest_ids: list[str]) -> int:
    from app.services import wa_contacts

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        flow = wa_contacts.active_flow(db, tenant_id, flow_id)
        if not flow:   # switched off since the batch was queued: stop quietly, nothing half-sent
            log.info("wa_contacts_enrol_skipped_inactive", tenant_id=tenant_id, flow_id=flow_id)
            return 0
        started = wa_contacts.start_flow_for(db, tenant_id, flow, guest_ids)
        log.info("wa_contacts_enrol_batch_done", tenant_id=tenant_id, flow_id=flow_id, started=started,
                 batch=len(guest_ids))
        return started
    finally:
        db.close()
