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
from app.models.guest_identity import GuestIdentity, IdentityType
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

        identity = (
            db.query(GuestIdentity)
            .filter_by(
                tenant_id=tenant_id,
                guest_id=guest.id,
                identity_type=IdentityType.INSTAGRAM_USER_ID,
            )
            .first()
        )
        sender_id = identity.identity_value if identity else ""
        if not sender_id:
            return {"status": "error", "reason": "guest has no instagram_user_id identity"}

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

        # Send — typing indicator and mark_seen are cosmetic, not required for
        # delivery, so they're dispatched as fire-and-forget tasks below instead
        # of blocking the critical path with two extra Meta API round trips.
        result = adapter.send_text(recipient_id=sender_id, text=message.body)
        ig_message_id = result.get("message_id", "")

        # Mark sent
        message.channel_message_id = ig_message_id
        message.channel_status = "sent"
        db.commit()

        # Notify SSE subscribers so the inbox updates the delivery tick without a page refresh
        try:
            import redis as _redis
            from app.core.config import settings as _settings
            import json as _json
            _r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            _r.publish(f"sse:{tenant_id}", _json.dumps({
                "event": "message_sent",
                "conversation_id": message.conversation_id,
                "channel": "instagram",
            }))
            _r.close()
        except Exception as _sse_exc:
            logger.warning("sse_publish_failed: %s", _sse_exc)

        instagram_mark_seen.delay(
            access_token=access_token, ig_account_id=ig_account_id, sender_id=sender_id,
        )

        logger.info("Sent Instagram DM: ig_mid=%s to=%s guest=%s", ig_message_id, sender_id, guest.id)
        return {"status": "sent", "ig_message_id": ig_message_id}

    except Exception as exc:
        logger.error("send_instagram_dm failed for message %s: %s", message_id, exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="instagram_mark_seen")
def instagram_mark_seen(access_token: str, ig_account_id: str, sender_id: str) -> None:
    """Fire-and-forget 'seen' receipt — cosmetic, never blocks the send path."""
    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    try:
        InstagramGraphAdapter(access_token=access_token, ig_account_id=ig_account_id).mark_seen(sender_id)
    except Exception as exc:
        logger.warning("instagram_mark_seen failed: %s", exc)
