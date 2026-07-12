"""
Celery task: process an inbound Instagram DM.

Flow (M2 — Instagram Identity Flow):
  receive webhook → resolve_or_create(instagram_user_id)
                 → find/create conversation → store message
                 → trigger concierge_draft

Identity is now managed by the progressive identity graph.
A guest is created with just their Instagram ID — phone is not required.
Later, when they share a WhatsApp number or book, enrich_guest() links the signals.
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.integration import Integration
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.core.encryption import decrypt_credentials
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="process_instagram_dm")
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

        # ── Find the tenant's Instagram integration by ig_account_id ───────
        # Multiple tenants may each have an active Instagram integration, so
        # matching must be scoped to the account this webhook was for, not
        # just "the first active one" (which picks an arbitrary tenant).
        candidates = db.query(Integration).filter_by(kind="instagram", status="active").all()
        integration = next(
            (c for c in candidates if (c.config or {}).get("instagram_business_account_id") == ig_account_id),
            None,
        )
        if not integration:
            logger.warning("Instagram DM received but no matching active integration for account %s", ig_account_id)
            return {"status": "skipped", "reason": "no integration"}

        tenant_id = integration.tenant_id
        set_tenant_context(db, tenant_id)

        # ── Dedup by message_id ────────────────────────────────────────────
        if mid:
            existing = db.query(Message).filter_by(channel_message_id=mid).first()
            if existing:
                return {"status": "duplicate", "message_id": mid}

        # ── Resolve or create guest via Identity Resolution Engine (M2) ─────
        # Try to fetch IG display name for new guest creation
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

        from app.services.identity_resolution import resolve_or_create
        guest_id, created = resolve_or_create(
            db=db,
            tenant_id=tenant_id,
            identity_type="instagram_user_id",
            identity_value=sender_id,
            source="instagram",
            guest_fields={"name": display_name},
        )
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if created:
            logger.info("Created new guest from Instagram DM: %s (%s)", guest_id, display_name)
        else:
            logger.debug("Resolved existing guest from Instagram DM: %s", guest_id)
            # Backfill: earlier messages may have stored the placeholder name
            # because the profile fetch failed at the time (e.g. before the
            # graph.instagram.com host fix). Update it once a real name is available.
            if guest and guest.name and guest.name.startswith("IG User ") and not display_name.startswith("IG User "):
                guest.name = display_name
                db.commit()

        # ── Find or create open conversation ────────────────────────────────
        channel_val = ChannelType.INSTAGRAM if hasattr(ChannelType, "INSTAGRAM") else "instagram"
        conversation = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id, is_open=True)
            .filter(Conversation.channel == channel_val)
            .first()
        )

        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                guest_id=guest_id,
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
        conversation.last_message_at = datetime.now(timezone.utc).isoformat()
        db.flush()
        db.commit()

        logger.info(
            "Stored Instagram DM: message=%s guest=%s conversation=%s",
            message.id, guest_id, conversation.id,
        )

        # Notify SSE subscribers so the inbox updates without a page refresh
        try:
            import redis as _redis
            from app.core.config import settings as _settings
            _r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            import json as _json
            _r.publish(f"sse:{tenant_id}", _json.dumps({
                "event": "message_received",
                "conversation_id": conversation.id,
                "channel": "instagram",
            }))
            _r.close()
        except Exception as _sse_exc:
            logger.warning("sse_publish_failed: %s", _sse_exc)

        # ── Trigger AI concierge draft ─────────────────────────────────────
        if body and body.strip() and not body.startswith("["):
            try:
                from app.workers.tasks.concierge_draft import concierge_draft
                concierge_draft.apply_async(
                    kwargs={
                        "message_id": message.id,
                        "conversation_id": conversation.id,
                        "tenant_id": tenant_id,
                    },
                    countdown=2,
                )
            except Exception as exc:
                logger.error("Failed to queue Instagram concierge draft: %s", exc)

        return {
            "status": "ok",
            "message_id": message.id,
            "guest_id": guest_id,
            "conversation_id": conversation.id,
        }

    except Exception as exc:
        logger.error("process_instagram_dm failed: %s", exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
