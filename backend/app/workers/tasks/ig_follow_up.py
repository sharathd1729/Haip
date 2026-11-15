"""The one follow-up after an Instagram keyword DM (Instagram toolkit phase 5; services/ig_quick_reply.send_follow_up).
Queued with a countdown by dispatch_quick_reply; sent only if the guest has not answered. Queue: whatsapp."""
import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()


@shared_task(name="ig_quick_reply.follow_up")
def send_follow_up(tenant_id: str, rule_id: str, recipient_id: str, guest_id: str, conversation_id: str, sent_at: str):
    from app.services import ig_quick_reply

    with SessionLocal() as db:
        try:
            outcome = ig_quick_reply.send_follow_up(db, tenant_id, rule_id, recipient_id, guest_id, conversation_id, sent_at)
            db.commit()
            log.info("ig_follow_up_done", tenant_id=tenant_id, rule_id=rule_id, outcome=outcome)
        except Exception:  # noqa: BLE001 -- one lost follow-up is acceptable; never retry into a second message
            db.rollback()
            log.exception("ig_follow_up_crashed", tenant_id=tenant_id, rule_id=rule_id)
