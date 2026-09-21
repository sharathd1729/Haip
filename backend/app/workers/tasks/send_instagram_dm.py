"""
Celery task: send an outbound Instagram DM.

Called by concierge_draft when channel == "instagram" and the message
has been approved (or autonomous mode with confidence >= threshold).
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.conversation import Message, Conversation, MessageDeliveryState
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Meta's Messenger-Platform-style error for "the guest hasn't messaged us in
# the last 24 hours" -- error_subcode 2018278 is the documented value for
# Messenger; not independently confirmed against a live Instagram Graph API
# occurrence (the diagnostic POST that would have confirmed it was correctly
# blocked as a real send action), so the message-text fallback below is the
# one actually verified against this incident.
_OUTSIDE_WINDOW_SUBCODE = 2018278
_OUTSIDE_WINDOW_PHRASES = ("outside of allowed window", "outside the allowed window")


def _meta_error_detail(exc: Exception) -> tuple[str, bool]:
    """Returns (human-readable detail, is_outside_messaging_window).

    meta_graph.py's _post() already logs exc.response.text on failure, but
    that never made it into delivery_error -- only httpx's generic
    exception summary did, which is why a Meta permission/window rejection
    read as an opaque "Max retries exceeded" in the inbox instead of
    something an agent could act on."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return str(exc), False

    try:
        body = exc.response.json()
        err = body.get("error", {})
        message = err.get("message", "") or exc.response.text[:300]
        subcode = err.get("error_subcode")
    except Exception:
        message = exc.response.text[:300]
        subcode = None

    is_window = subcode == _OUTSIDE_WINDOW_SUBCODE or any(
        phrase in message.lower() for phrase in _OUTSIDE_WINDOW_PHRASES
    )
    return message, is_window


# Meta: one private reply per comment, within 7 days of the comment.
_PRIVATE_REPLY_MAX_AGE_SECONDS = 7 * 86400


class _CommentReplyBlocked(Exception):
    """A reply to a comment that Meta's private-reply rules won't allow."""


def _private_reply_target(db: Session, message: Message) -> str | None:
    """comment_id to answer privately, if the guest's latest message in this
    conversation is an Instagram comment rather than a DM.

    Confirmed live on Ratha: every failed AI reply over 2 days answered a
    comment ("Bhadra.", "We had enquired earlier but no response") with a
    plain DM, which Meta rejects as "outside of allowed window" because the
    person never DM'd. A reply to a comment has to go out as a private reply
    tied to that comment. Raises _CommentReplyBlocked when Meta's limits
    (once per comment, within 7 days) rule it out."""
    latest_in = (
        db.query(Message)
        .filter(
            Message.conversation_id == message.conversation_id,
            Message.tenant_id == message.tenant_id,
            Message.direction == "inbound",
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    meta = (latest_in.channel_metadata or {}) if latest_in else {}
    if meta.get("source") != "comment" or not meta.get("comment_id"):
        return None
    comment_id = meta["comment_id"]

    created = latest_in.created_at
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - created).total_seconds() > _PRIVATE_REPLY_MAX_AGE_SECONDS:
            raise _CommentReplyBlocked(
                "This guest only commented on a post, over 7 days ago -- Instagram no longer "
                "allows a private reply. They need to send us a DM first."
            )

    already = (
        db.query(Message.id)
        .filter(
            Message.conversation_id == message.conversation_id,
            Message.tenant_id == message.tenant_id,
            Message.id != message.id,
            Message.delivery_state.in_([
                MessageDeliveryState.SENT, MessageDeliveryState.DELIVERED, MessageDeliveryState.READ,
            ]),
            Message.channel_metadata["private_reply_comment_id"].as_string() == comment_id,
        )
        .first()
    )
    if already:
        raise _CommentReplyBlocked(
            "Already replied privately to this comment -- Instagram allows one reply per "
            "comment. The conversation continues once the guest replies to that message."
        )
    return comment_id


def _mark_failed(db: Session, message: Message, reason: str) -> None:
    """Transition message to FAILED and record the reason -- mirrors
    send_whatsapp.py's _mark_failed so both channels give the inbox UI the
    same delivery-tick contract instead of leaving the draft stuck at
    QUEUED forever on any of these early-exit paths."""
    try:
        message.delivery_state = MessageDeliveryState.FAILED
        message.delivery_error = reason[:500]
        message.channel_status = "failed"
        db.commit()
        logger.warning("send_instagram_dm_marked_failed: message=%s reason=%s", message.id, reason)
    except Exception:
        pass


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
            _mark_failed(db, message, "Guest not found for conversation")
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
            _mark_failed(db, message, "Guest has no instagram_user_id identity signal")
            return {"status": "error", "reason": "guest has no instagram_user_id identity"}

        # Get integration credentials
        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="instagram", status="active"
        ).first()
        if not integration:
            _mark_failed(db, message, "Instagram integration not connected")
            return {"status": "error", "reason": "Instagram integration not connected"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        access_token = creds.get("access_token", "")
        ig_account_id = (integration.config or {}).get("instagram_business_account_id", "")

        if not access_token or not ig_account_id:
            _mark_failed(db, message, "Missing access_token or instagram_business_account_id in integration config")
            return {"status": "error", "reason": "missing access_token or ig_account_id"}

        from app.adapters.instagram.meta_graph import InstagramGraphAdapter
        adapter = InstagramGraphAdapter(
            access_token=access_token,
            ig_account_id=ig_account_id,
        )

        # Send — typing indicator and mark_seen are cosmetic, not required for
        # delivery, so they're dispatched as fire-and-forget tasks below instead
        # of blocking the critical path with two extra Meta API round trips.
        try:
            comment_id = _private_reply_target(db, message)
        except _CommentReplyBlocked as blocked:
            _mark_failed(db, message, str(blocked))
            return {"status": "error", "reason": "comment_reply_blocked"}

        if comment_id:
            result = adapter.send_private_reply(comment_id=comment_id, text=message.body)
            message.channel_metadata = {**(message.channel_metadata or {}), "private_reply_comment_id": comment_id}
        else:
            result = adapter.send_text(recipient_id=sender_id, text=message.body)
        ig_message_id = result.get("message_id", "")

        # Mark sent -- delivery_state wasn't set here at all (send_whatsapp's
        # equivalent sets QUEUED->SENT/FAILED), so an approved Instagram
        # draft sat at QUEUED forever in the UI even on a successful send.
        message.channel_message_id = ig_message_id
        message.channel_status = "sent"
        message.delivery_state = MessageDeliveryState.SENT
        message.delivery_error = None
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
        detail, is_outside_window = _meta_error_detail(exc)

        if is_outside_window:
            # Confirmed live: Instagram rejects every send once the guest
            # hasn't messaged in 24h, with the same error on every retry --
            # retrying wastes 3 rounds of Celery backoff for something that
            # only a fresh inbound message from the guest can fix. No
            # rollback here -- the exception fires on the external HTTP
            # call, before this function touches the DB, so there is
            # nothing uncommitted to discard.
            try:
                msg = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
                if msg:
                    _mark_failed(
                        db, msg,
                        "Instagram won't deliver this -- the guest hasn't messaged in "
                        "over 24 hours, so we can't message them first. Ask them to "
                        f"send anything to reopen the conversation. (Meta: {detail})",
                    )
            except Exception:
                pass
            return {"status": "error", "reason": "outside_24h_window"}

        if self.request.retries >= self.max_retries:
            try:
                msg = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
                if msg:
                    _mark_failed(db, msg, f"Max retries exceeded: {detail}")
            except Exception:
                pass
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
