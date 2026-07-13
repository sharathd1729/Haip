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
from urllib.parse import urlparse
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.integration import Integration
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.core.encryption import decrypt_credentials
from app.adapters.instagram.meta_graph import validate_media_url
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
        referral = payload.get("referral") or None  # T0.3: ad-attribution, if present

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
        # T0.4: use the placeholder name immediately rather than blocking this
        # latency-critical path on a Graph API round trip for every new guest.
        # backfill_instagram_guest_name (below) fetches the real name as a
        # fire-and-forget follow-up after the message is already visible.
        display_name = f"IG User {sender_id[-6:]}"

        from app.services.identity_service import resolve_gid
        guest_id, created = resolve_gid(
            db=db,
            tenant_id=tenant_id,
            signal_type="instagram_user_id",
            value=sender_id,
            source="instagram",
            guest_fields={"name": display_name},
        )
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if created:
            logger.info("Created new guest from Instagram DM: %s (%s)", guest_id, display_name)
        else:
            logger.debug("Resolved existing guest from Instagram DM: %s", guest_id)

        # T0.4: fire-and-forget real-name fetch. Dispatched whenever the guest
        # still has a placeholder name (new guest, or an earlier message whose
        # own backfill attempt failed) -- never blocks this task.
        if guest and guest.name and guest.name.startswith("IG User "):
            backfill_instagram_guest_name.apply_async(
                kwargs={"tenant_id": tenant_id, "guest_id": guest_id, "sender_id": sender_id},
                countdown=1,
            )

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
                # T3.2: inherit the tenant's Instagram AI default rather than
                # a hardcoded "shadow" for every tenant regardless of risk tolerance.
                ai_mode=integration.tenant.ig_ai_mode_default if integration.tenant else "shadow",
            )
            db.add(conversation)
            db.flush()

        # ── Store message ──────────────────────────────────────────────────
        body = text or ""
        media_url = None
        media_type = None
        shared_post_url = None
        # Post/story-share attachments (type "ig_post"/"share"/"story_mention") link
        # to a permalink, not a fetchable CDN media file -- validate_media_url()
        # correctly rejects these (they're not on Meta's CDN host allowlist), but
        # the permalink itself is still useful to show, just as an outbound link
        # rather than fetched/rendered media. Only genuine CDN attachment URLs are
        # ever treated as media_url.
        if attachments:
            att = attachments[0]
            att_type = att.get("type", "media")
            att_url = (att.get("payload") or {}).get("url", "")
            if not body:
                body = f"[{att_type}]"  # fallback caption, not a replacement for the URL
            if att_url and validate_media_url(att_url):
                media_url = att_url
                media_type = att_type
            elif att_url:
                if att_type in ("ig_post", "share", "story_mention"):
                    shared_post_url = att_url
                else:
                    logger.warning(
                        "Instagram attachment URL failed SSRF allowlist check, dropping media_url: host=%s",
                        urlparse(att_url).netloc,
                    )

        channel_metadata = {}
        if referral:
            channel_metadata["referral"] = referral
        if shared_post_url:
            channel_metadata["shared_post_url"] = shared_post_url

        message = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_message_id=mid or str(uuid.uuid4()),
            direction=MessageDirection.INBOUND,
            channel=channel_val,
            body=body,
            media_url=media_url,
            media_type=media_type,
            channel_status="received",
            channel_metadata=channel_metadata or None,
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
                "guest_name": guest.name if guest else display_name,
                "preview": body[:120],
            }))
            _r.close()
        except Exception as _sse_exc:
            logger.warning("sse_publish_failed: %s", _sse_exc)

        # ── T2/T3: keyword-match first; AI concierge draft is fallback only ──
        # Priority 3 requirement: auto-reply always wins when both would
        # otherwise fire. AI is strictly for messages no rule matched.
        matched_rule = None
        if body and body.strip() and not body.startswith("["):
            from app.services.ig_keyword_match import find_matching_rule
            matched_rule = find_matching_rule(db, tenant_id, "ig_dm_received", body)

        if matched_rule:
            from app.services.ig_quick_reply import dispatch_quick_reply
            dispatch_quick_reply(
                db, tenant_id, matched_rule,
                recipient_id=sender_id, guest_id=guest_id, conversation_id=conversation.id,
            )
        elif body and body.strip() and not body.startswith("[") and conversation.ai_mode != "off":
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


@celery_app.task(bind=True, name="backfill_instagram_guest_name", max_retries=3, default_retry_delay=30)
def backfill_instagram_guest_name(self, tenant_id: str, guest_id: str, sender_id: str) -> dict:
    """
    T0.4: fire-and-forget follow-up to process_instagram_dm. Fetches the
    guest's real Instagram display name via the Graph API and updates it if
    it's still the "IG User ######" placeholder -- run off the critical path
    so new-guest messages never wait on this external round trip.
    """
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if not guest or not guest.name or not guest.name.startswith("IG User "):
            return {"status": "skipped", "reason": "guest already named or not found"}

        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="instagram", status="active"
        ).first()
        if not integration:
            return {"status": "skipped", "reason": "no integration"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        access_token = creds.get("access_token", "")
        account_id = (integration.config or {}).get("instagram_business_account_id", "")
        if not access_token or not account_id:
            return {"status": "skipped", "reason": "missing credentials"}

        from app.adapters.instagram.meta_graph import InstagramGraphAdapter
        ig_adapter = InstagramGraphAdapter(access_token=access_token, ig_account_id=account_id)
        profile = ig_adapter.get_user_profile(sender_id)
        real_name = profile.get("name", "")

        if real_name and not real_name.startswith("IG User "):
            guest.name = real_name
            db.commit()
            logger.info("Backfilled Instagram guest name: %s -> %s", guest_id, real_name)
            return {"status": "ok", "guest_id": guest_id, "name": real_name}

        return {"status": "no_name_available"}
    except Exception as exc:
        # 4xx from the Graph API (permission denied, user not found, etc.) will
        # never succeed on retry -- give up permanently on those. Anything else
        # (timeouts, 5xx, network errors) is transient -- retry with backoff.
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code and 400 <= status_code < 500:
            logger.warning(
                "backfill_instagram_guest_name permanently failed for guest %s: %s", guest_id, exc
            )
            return {"status": "error", "reason": str(exc)}
        logger.warning(
            "backfill_instagram_guest_name failed for guest %s (will retry): %s", guest_id, exc
        )
        raise self.retry(exc=exc)
    finally:
        db.close()
