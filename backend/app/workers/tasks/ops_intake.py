"""Staff WhatsApp photos for ops files (services/ops_photo_intake.py). Queue: ai_scoring (a vision model reads the photo).

ops.process_staff_photo  download the photo from Meta, read it, apply it to the person's trip, reply to them, alert the
                         manager on a flag. A redelivered message is handled once (Redis key per message id). A provider
                         outage is retried twice; anything else gets a "please resend" reply, never a silent drop.
"""

import asyncio

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()

MAX_RETRIES = 2


def _fetch(token: str, media_id: str) -> tuple[bytes, str]:
    from app.adapters.whatsapp.meta_cloud import MetaCloudAdapter

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(MetaCloudAdapter(phone_number_id="", access_token=token).fetch_media(media_id))
    finally:
        loop.close()


@shared_task(name="ops.process_staff_photo", bind=True, max_retries=MAX_RETRIES)
def process_staff_photo(self, tenant_id: str, staff_id: str, media_id: str, caption: str, message_id: str):
    from app.adapters.vision import VisionError, VisionModelBlocked
    from app.core.cache import get_cached, set_cached
    from app.models.ops import StaffProfile
    from app.services import lead_alert_sender, ops_photo_intake
    from app.workers.tasks.ops_escalation import queue_delivery

    done_key = f"haip:ops:photo:{message_id}"
    if message_id and get_cached(done_key):
        return
    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        staff = db.query(StaffProfile).filter_by(id=staff_id, tenant_id=tenant_id, active=True).first()
        if staff is None:
            return
        reply = "Could not read that photo. Please send it again."
        sends: list[str] = []
        try:
            _, token = lead_alert_sender.wa_credentials(db, tenant_id)
            if not token:
                log.error("ops_photo_no_whatsapp", tenant_id=tenant_id)
                return
            raw, _mime = _fetch(token, media_id)
            out = ops_photo_intake.handle_photo(db, tenant_id, staff, raw=raw, caption=caption, message_id=message_id)
            db.commit()
            reply, sends = out.reply, out.send_ids
            if message_id:
                set_cached(done_key, "1", ttl=86400)
        except VisionError as exc:
            db.rollback()
            if exc.transient and self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=30 * (2**self.request.retries)) from exc
            log.warning(
                "ops_photo_vision_failed",
                tenant_id=tenant_id,
                staff_id=staff_id,
                error=str(exc)[:200],
            )
        except VisionModelBlocked as exc:
            db.rollback()
            log.error("ops_photo_vision_blocked", tenant_id=tenant_id, error=str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 -- the sender is always answered; the error is logged loudly
            db.rollback()
            log.error(
                "ops_photo_failed",
                tenant_id=tenant_id,
                staff_id=staff_id,
                error=str(exc)[:300],
            )
        queue_delivery(tenant_id, sends)
        lead_alert_sender.send_text(db, tenant_id, staff.phone_e164, reply)
