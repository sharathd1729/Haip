"""
Celery task: process an inbound Instagram comment.

T1.2 — mirrors process_instagram_dm.py's structure (identity via
identity_service, deferred profile-name fetch, SSE publish with
guest_name/preview) with a comment-specific dedupe key and
channel_metadata tagging so comment-origin messages are distinguishable
from DMs within the same guest conversation.

Flow: dedupe by comment_id → resolve identity → find/create conversation
    → store message (tagged channel_metadata.source == "comment")
    → publish SSE → [Phase 2: keyword-match against automation_rules,
    reply + stop if matched] → else queue concierge_draft as fallback.

Phase 2 (keyword auto-reply) and Phase 3 (fallback gating) are not yet
built -- see Architecture Decision #3 in the Instagram module build
plan. Until then this always falls through to the AI concierge draft,
same as process_instagram_dm today.
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
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="process_instagram_comment")
def process_instagram_comment(self, payload: dict) -> dict:
    """
    payload keys:
      ig_account_id  — the business Instagram account ID
      sender_id      — Instagram-scoped user ID of the commenter
      comment_id     — Meta comment ID
      text           — comment text
      media_id       — the post/reel the comment was made on
      media_ad_id    — present if the post is a running ad
      media_ad_title — ad title, if applicable
    """
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        ig_account_id = payload.get("ig_account_id", "")
        sender_id = payload.get("sender_id", "")
        comment_id = payload.get("comment_id", "")
        text = payload.get("text", "")
        media_id = payload.get("media_id", "")
        media_ad_id = payload.get("media_ad_id", "")
        media_ad_title = payload.get("media_ad_title", "")

        if not sender_id or not comment_id:
            return {"status": "skipped", "reason": "no sender_id or comment_id"}

        # ── Find the tenant's Instagram integration by ig_account_id ───────
        candidates = db.query(Integration).filter_by(kind="instagram", status="active").all()
        integration = next(
            (c for c in candidates if (c.config or {}).get("instagram_business_account_id") == ig_account_id),
            None,
        )
        if not integration:
            logger.warning("Instagram comment received but no matching active integration for account %s", ig_account_id)
            return {"status": "skipped", "reason": "no integration"}

        tenant_id = integration.tenant_id
        set_tenant_context(db, tenant_id)

        # ── Dedup by comment_id ─────────────────────────────────────────────
        existing = db.query(Message).filter_by(channel_message_id=f"comment_{comment_id}").first()
        if existing:
            return {"status": "duplicate", "comment_id": comment_id}

        # ── Resolve or create guest via identity_service (T0.1 pattern) ─────
        # Same identity signal as DMs -- a commenter and a DM sender are the
        # same Instagram-scoped user ID, so they resolve to the same guest.
        display_name = f"IG User {sender_id[-6:]}"

        from app.services.identity_service import resolve_gid
        guest_id, created = resolve_gid(
            db=db,
            tenant_id=tenant_id,
            signal_type="instagram_user_id",
            value=sender_id,
            source="instagram_comment",
            guest_fields={"name": display_name},
        )
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if created:
            logger.info("Created new guest from Instagram comment: %s (%s)", guest_id, display_name)

        # T0.4 pattern: defer the profile-name fetch, never block ingest on it.
        if guest and guest.name and guest.name.startswith("IG User "):
            from app.workers.tasks.process_instagram_dm import backfill_instagram_guest_name
            backfill_instagram_guest_name.apply_async(
                kwargs={"tenant_id": tenant_id, "guest_id": guest_id, "sender_id": sender_id},
                countdown=1,
            )

        # ── Find or create open conversation (shared with DMs) ──────────────
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

        # ── Store message, tagged as a comment (not a DM) ────────────────────
        channel_meta = {"source": "comment", "comment_id": comment_id, "media_id": media_id}
        if media_ad_id:
            channel_meta["media_ad_id"] = media_ad_id
            channel_meta["media_ad_title"] = media_ad_title

        message = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_message_id=f"comment_{comment_id}",
            direction=MessageDirection.INBOUND,
            channel=channel_val,
            body=text or "[comment]",
            channel_status="received",
            channel_metadata=channel_meta,
        )
        db.add(message)
        conversation.last_message_at = datetime.now(timezone.utc).isoformat()
        db.flush()
        db.commit()

        logger.info(
            "Stored Instagram comment: message=%s guest=%s conversation=%s comment=%s",
            message.id, guest_id, conversation.id, comment_id,
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
                "preview": (text or "[comment]")[:120],
            }))
            _r.close()
        except Exception as _sse_exc:
            logger.warning("sse_publish_failed: %s", _sse_exc)

        # ── Phase 2 (not yet built): keyword-match against automation_rules
        # for trigger="ig_comment_received" would go here, inline, before the
        # AI fallback below -- first match wins, dual public+private reply,
        # log to automation_runs, and skip concierge_draft entirely if matched.
        # See Architecture Decision #2/#3 and T2.1-T2.3.

        # ── Trigger AI concierge draft (fallback -- unconditional until
        # Phase 2/3 ship the keyword-match gate) ─────────────────────────────
        if text and text.strip():
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
                logger.error("Failed to queue Instagram comment concierge draft: %s", exc)

        return {
            "status": "ok",
            "message_id": message.id,
            "guest_id": guest_id,
            "conversation_id": conversation.id,
        }

    except Exception as exc:
        logger.error("process_instagram_comment failed: %s", exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
