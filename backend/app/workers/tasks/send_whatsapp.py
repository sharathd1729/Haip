"""
Send WhatsApp message task — uses MetaCloudAdapter.

Delivery state transitions managed here:
  QUEUED → SENT      on Meta API 200
  QUEUED → FAILED    on retry exhaustion or permanent error
"""
import asyncio
from datetime import datetime, timezone
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message, MessageDeliveryState
from app.models.integration import Integration
from app.adapters.whatsapp.meta_cloud import get_wa_adapter
import structlog

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=5, default_retry_delay=30, name="tasks.send_whatsapp")
def send_whatsapp(self, message_id: str, tenant_id: str):
    db = SessionLocal()
    try:
        message = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
        if not message:
            log.error("send_whatsapp_message_not_found", message_id=message_id)
            return

        conversation = db.query(Conversation).filter_by(id=message.conversation_id).first()
        if not conversation:
            log.error("send_whatsapp_conv_not_found", conversation_id=message.conversation_id)
            return

        # Get WhatsApp integration credentials for this tenant
        integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
        if not integration:
            log.error("send_whatsapp_no_integration", tenant_id=tenant_id)
            _mark_failed(db, message, "No WhatsApp integration configured for tenant")
            return

        config = integration.config or {}
        phone_number_id = config.get("phone_number_id")
        access_token = config.get("access_token")

        if not phone_number_id or not access_token:
            log.error("send_whatsapp_missing_credentials", tenant_id=tenant_id)
            _mark_failed(db, message, "Missing phone_number_id or access_token in integration config")
            return

        # Get recipient phone from guest
        from app.models.guest import Guest
        guest = db.query(Guest).filter_by(id=conversation.guest_id).first()
        if not guest:
            _mark_failed(db, message, "Guest not found for conversation")
            return

        adapter = get_wa_adapter(phone_number_id, access_token)

        def _run_async(coro):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

        result = _run_async(adapter.send_text(to=guest.phone, body=message.body or ""))

        # ── Success: transition to SENT ───────────────────────────────────────
        wamid = result.get("messages", [{}])[0].get("id")
        message.channel_message_id = wamid
        message.channel_status = "sent"
        message.delivery_state = MessageDeliveryState.SENT
        message.delivery_error = None
        message.was_approved = True
        db.commit()

        log.info(
            "whatsapp_sent",
            message_id=message_id,
            wamid=wamid,
            to=guest.phone,
        )

    except Exception as exc:
        error_str = str(exc)
        log.error("send_whatsapp_failed", message_id=message_id, error=error_str)

        # On final retry exhaustion → mark permanently FAILED
        if self.request.retries >= self.max_retries:
            _mark_failed(db, message, f"Max retries exceeded: {error_str}")

        raise self.retry(exc=exc)
    finally:
        db.close()


def _mark_failed(db, message: Message, reason: str) -> None:
    """Transition message to FAILED and record the reason."""
    try:
        message.delivery_state = MessageDeliveryState.FAILED
        message.delivery_error = reason[:500]  # cap length
        message.channel_status = "failed"
        db.commit()
        log.warning(
            "send_whatsapp_marked_failed",
            message_id=message.id,
            reason=reason,
        )
    except Exception:
        pass  # never let cleanup crash the task
