"""One follow-up message of an Instagram automation's sequence (services/ig_sequence.py). Queued with a countdown;
sends only if nobody has written since the sequence started and Instagram's window is open. Queue: whatsapp."""

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()


@shared_task(name="ig_sequence.step")
def send_step(
    tenant_id: str, rule_id: str, guest_id: str, conversation_id: str, recipient_id: str, step: int, started_at: str
):
    from app.services import ig_sequence

    with SessionLocal() as db:
        try:
            set_tenant_context(db, tenant_id)
            outcome = ig_sequence.send_step(
                db, tenant_id, rule_id, guest_id, conversation_id, recipient_id, step, started_at
            )
            log.info("ig_sequence_step_done", tenant_id=tenant_id, rule_id=rule_id, step=step, outcome=outcome)
        except Exception:  # noqa: BLE001 -- never retry into a duplicate message
            db.rollback()
            log.exception("ig_sequence_step_crashed", tenant_id=tenant_id, rule_id=rule_id, step=step)
