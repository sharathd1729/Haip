"""The one nudge in an Instagram DM form (services/ig_dm_form.py): queued with a countdown each time a question is
asked; sent only if the person is still on that question and hasn't been nudged. Queue: whatsapp."""

import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()


@shared_task(name="ig_dm_form.remind")
def remind(tenant_id: str, session_id: str, step: int):
    from app.services import ig_dm_form

    with SessionLocal() as db:
        try:
            outcome = ig_dm_form.remind(db, tenant_id, session_id, step)
            log.info("ig_form_reminder_done", tenant_id=tenant_id, session_id=session_id, outcome=outcome)
        except Exception:  # noqa: BLE001 -- one lost nudge is acceptable; never retry into a second message
            db.rollback()
            log.exception("ig_form_reminder_crashed", tenant_id=tenant_id, session_id=session_id)
