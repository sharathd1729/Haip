"""
Celery task: process an inbound Instagram DM.

Flow:
  receive webhook → process_instagram_dm → upsert guest (by ig_sender_id)
                 → find/create conversation → store message
                 → trigger concierge_draft

Instagram senders are identified by their Instagram-scoped user ID.
We store it in guest.preferences["instagram_id"] for lookup.
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.integration import Integration
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.core.encryption import decrypt_credentials

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="process_instagram_dm")
def process_instagram_dm(self, payload: dict) -> dict:
    """
    payload keys:
      ig_account_id  — the business Instagram account ID
      sender_id      — Instagram-scoped user ID of the sender
      message_id     — Meta message ID (mid)
      text           — message text (may be empty for media)
      attachments    — list of attachment objects
      timestamp      — Unix ms timestamp
    """
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        ig_account_id = payload.get("ig_account_id", "")
        sender_id = payload.get("sender_id", "")
        mid = payload.get("message_id", "")
        text = payload.get("text", "")
        attachments = payload.get("attachments", [])

        if not sender_id:
            return {"status": "skipped", "reason": "no sender_id"}

        # ── Find active Instagram integration ──────────────────────────────
        integration = db.query(Integration).filter_by(
            kind="instagram", status="active"
        ).first()
        if not integration:
            logger.warning("Instagram DM received but no active Instagram integration")
            return {"status": "skipped", "reason": "no integration"}

        tenant_id = integration.tenant_id
        set_tenant_context(db, tenant_id)

        # ── Dedup by message_id ────────────────────────────────────────────
        if mid:
            existing = db.query(Message).filter_by(channel_message_id=mid).first()
            if existing:
                return {"status": "duplicate", "message_id": mid}

        # ── Upsert guest by instagram_id (stored in preferences) ──────────
        # Use a JSONB containment query instead of loading all guests (N+1 fix)
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        guest = db.query(Guest).filter(
            Guest.tenant_id == tenant_id,
            Guest.is_deleted == False,
            Guest.preferences.op("@>")(cast({"instagram_id": sender_id}, JSONB)),
        ).first()

        if not guest:
            # Try to fetch name from Instagram Graph API
            display_name = f"IG User {sender_id[-6:]}"
            try:
                creds = decrypt_credentials(integration.credentials_kms_blob)
                access_token = creds.get("access_token", "")
                ig_config = integration.config or {}
                account_id = ig_config.get("instagram_business_account_id", "")
                if access_token and account_id:
                    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
                    ig_adapter = InstagramGraphAdapter(
                        access_token=access_token,
                        ig_account_id=account_id,
                    )
                    profile = ig_adapter.get_user_profile(sender_id)
                    display_name = profile.get("name", display_name)
            except Exception as exc:
                logger.debug("Could not fetch IG profile for %s: %s", sender_id, exc)

            guest = Guest(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                phone="",  # Instagram DMs have no phone number
                name=display_name,
                preferences={"instagram_id": sender_id},
            )
            db.add(guest)
            db.flush()
            logger.info("Created new guest from Instagram DM: %s (%s)", guest.id, display_name)
        else:
            # Ensure instagram_id is stored (in case it wasn't before)
            prefs = dict(guest.preferences or {})
            prefs["instagram_id"] = sender_id
            guest.preferences = prefs

        # ── Find or create open conversation ────────────────────────────────
        channel_val = ChannelType.INSTAGRAM if hasattr(ChannelType, "INSTAGRAM") else "instagram"
        conversation = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant_id, guest_id=guest.id, is_open=True)
            .filter(Conversation.channel == channel_val)
            .first()
        )

        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                guest_id=guest.id,
                channel=channel_val,
                is_open=True,
                ai_mode="shadow",
            )
            db.add(conversation)
            db.flush()

        # ── Store message ──────────────────────────────────────────────────
        body = text or ""
        if not body and attachments:
            att_type = attachments[0].get("type", "media")
            body = f"[{att_type}]"

        message = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_message_id=mid or str(uuid.uuid4()),
            direction=MessageDirection.INBOUND,
            channel=channel_val,
            body=body,
            channel_status="received",
        )
        db.add(message)
        db.flush()
        db.commit()

        logger.info(
            "Stored Instagram DM: message=%s guest=%s conversation=%s",
            message.id, guest.id, conversation.id,
        )

        # ── Trigger AI concierge draft ─────────────────────────────────────
        if body and body.strip() and not body.startswith("["):
            try:
                from app.workers.tasks.concierge_draft import concierge_draft
                concierge_draft.apply_async(
                    kwargs={
                        "message_id": message.id,
                        "conversation_id": conversation.id,
                        "tenant_id": tenant_id,
                        "channel": "instagram",
                    },
                    countdown=2,
                )
            except Exception as exc:
                logger.error("Failed to queue Instagram concierge draft: %s", exc)

        return {
            "status": "ok",
            "message_id": message.id,
            "guest_id": guest.id,
            "conversation_id": conversation.id,
        }

    except Exception as exc:
        logger.error("process_instagram_dm failed: %s", exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
