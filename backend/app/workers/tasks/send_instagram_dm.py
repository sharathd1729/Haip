"""
Celery task: send an outbound Instagram DM.

Called by concierge_draft when channel == "instagram" and the message
has been approved (or autonomous mode with confidence >= threshold).
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.conversation import Message, Conversation
from app.models.guest import Guest
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="send_instagram_dm")
def send_instagram_dm(self, message_id: str, tenant_id: str) -> dict:
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        message = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
        if not message:
            return {"status": "error", "reason": "message not found"}

        # Already sent?
        if (message.channel_message_id
                and not message.channel_message_id.startswith("draft_")
                and message.channel_status == "sent"):
            return {"status": "already_sent"}

        # Get conversation → guest → instagram_id
        conversation = db.query(Conversation).filter_by(id=message.conversation_id).first()
        guest = db.query(Guest).filter_by(id=conversation.guest_id).first() if conversation else None

        if not guest:
            return {"status": "error", "reason": "guest not found"}

        sender_id = (guest.preferences or {}).get("instagram_id", "")
        if not sender_id:
            return {"status": "error", "reason": "guest has no instagram_id in preferences"}

        # Get integration credentials
        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="instagram", status="active"
        ).first()
        if not integration:
            return {"status": "error", "reason": "Instagram integration not connected"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        access_token = creds.get("access_token", "")
        ig_account_id = (integration.config or {}).get("instagram_business_account_id", "")

        if not access_token or not ig_account_id:
            return {"status": "error", "reason": "missing access_token or ig_account_id"}

        from app.adapters.instagram.meta_graph import InstagramGraphAdapter
        adapter = InstagramGraphAdapter(
            access_token=access_token,
            ig_account_id=ig_account_id,
        )

        # Typing indicator
        try:
            adapter.typing_on(sender_id)
        except Exception:
            pass

        # Send
        result = adapter.send_text(recipient_id=sender_id, text=message.body)
        ig_message_id = result.get("message_id", "")

        # Mark sent
        message.channel_message_id = ig_message_id
        message.channel_status = "sent"
        db.commit()

        # Mark seen
        try:
            adapter.mark_seen(sender_id)
        except Exception:
            pass

        logger.info("Sent Instagram DM: ig_mid=%s to=%s guest=%s", ig_message_id, sender_id, guest.id)
        return {"status": "sent", "ig_message_id": ig_message_id}

    except Exception as exc:
        logger.error("send_instagram_dm failed for message %s: %s", message_id, exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
