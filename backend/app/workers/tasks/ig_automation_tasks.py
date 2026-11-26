"""Instagram automation tasks (queue whatsapp, exact-name routes in celery_app.py). Never retried: a retry could send a
second DM.

  ig_automation.start_delayed   run a matched rule after its "reply time" delay (ig_quick_reply.dispatch_quick_reply)
  ig_automation.send_existing   answer the comments a post already has (last 7 days) with a rule (ig_send_existing)
"""

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()


@shared_task(name="ig_automation.start_delayed")
def start_delayed(tenant_id: str, rule_id: str, recipient_id: str, guest_id: str | None, conversation_id: str | None,
                  comment_id: str | None = None, media_id: str | None = None) -> dict:
    from app.models.automation import AutomationRule
    from app.services.ig_quick_reply import dispatch_quick_reply

    with SessionLocal() as db:
        try:
            set_tenant_context(db, tenant_id)
            rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=tenant_id, is_active=True).first()
            if rule is None:
                return {"status": "skipped", "reason": "rule gone or off"}
            sent = dispatch_quick_reply(db, tenant_id, rule, recipient_id=recipient_id, guest_id=guest_id,
                                        conversation_id=conversation_id, comment_id=comment_id, media_id=media_id,
                                        delayed=True)
            return {"status": "sent" if sent else "not_sent"}
        except Exception:  # noqa: BLE001 -- never retry into a duplicate message
            db.rollback()
            log.exception("ig_automation_delayed_crashed", tenant_id=tenant_id, rule_id=rule_id)
            return {"status": "error"}


@shared_task(name="ig_automation.send_existing")
def send_existing(tenant_id: str, rule_id: str) -> dict:
    from app.services import ig_send_existing

    with SessionLocal() as db:
        try:
            set_tenant_context(db, tenant_id)
            out = ig_send_existing.run(db, tenant_id, rule_id)
            log.info("ig_automation_send_existing_done", tenant_id=tenant_id, rule_id=rule_id, **out)
            return out
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("ig_automation_send_existing_crashed", tenant_id=tenant_id, rule_id=rule_id)
            return {"status": "error"}
