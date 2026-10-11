"""
Instagram DM webhook receiver.

Meta sends the same webhook format for both WhatsApp and Instagram.
Register this URL in your Meta App → Webhooks → instagram → messages.

Verification:  GET /webhooks/instagram?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
Inbound DMs:   POST /webhooks/instagram  (X-Hub-Signature-256 header)
"""

import json
from secrets import compare_digest
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services import webhook_verify_service
from fastapi.responses import PlainTextResponse
from app.core.config import settings
from app.core.webhook_security import verify_meta_signature_any
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks-instagram"])


# ── Webhook verification (GET) ────────────────────────────────────────────────

@router.get("/instagram")
def verify_instagram_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    # Per-workspace Instagram token (a WhatsApp token does not verify here); legacy shared token
    # still accepted while ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN is on.
    if hub_mode == "subscribe" and webhook_verify_service.verify(db, "instagram", hub_verify_token):
        log.info("instagram_webhook_verified")
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


# ── Inbound DMs (POST) ────────────────────────────────────────────────────────

@router.post("/instagram")
async def receive_instagram_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("object") != "instagram":
        return {"status": "ignored"}

    # Tenant-stored app_secret for the integration matching this IG account.
    # Verified alongside the server's META_APP_SECRET below -- see
    # verify_meta_signature_any for why a wrong tenant value must not be
    # allowed to block inbound on its own.
    app_secret = ""
    entries = payload.get("entry", [])
    ig_account_id = entries[0].get("id") if entries else None

    if ig_account_id:
        try:
            from app.core.database import SessionLocal
            from app.models.integration import INSTAGRAM_INBOUND_STATUSES, Integration
            from app.core.encryption import decrypt_credentials
            _db = SessionLocal()
            try:
                # Same statuses the worker accepts: a workspace whose Meta app
                # has its own secret must still verify while its token is
                # marked bad, or the signature check 401s the DM before the
                # worker ever sees it.
                _candidates = (
                    _db.query(Integration)
                    .filter(Integration.kind == "instagram", Integration.status.in_(INSTAGRAM_INBOUND_STATUSES))
                    .all()
                )
                _ig = next(
                    (
                        c for c in _candidates
                        if (c.config or {}).get("instagram_business_account_id") == ig_account_id
                    ),
                    None,
                )
                if _ig:
                    _creds = decrypt_credentials(_ig.credentials_kms_blob)
                    app_secret = _creds.get("app_secret", "")
            finally:
                _db.close()
        except Exception as _e:
            log.warning("instagram_webhook_secret_lookup_failed", error=str(_e))

    # Raises 401 when no held secret matches; in dev with none configured it
    # logs a warning and continues.
    matched = verify_meta_signature_any(
        body=body,
        signature_header=sig,
        env=settings.ENVIRONMENT,
        secrets=[("tenant_app_secret", app_secret), ("META_APP_SECRET", settings.META_APP_SECRET)],
    )
    if app_secret and matched == "META_APP_SECRET":
        # Accepted, but the secret saved on the integration is wrong. Loud so
        # it gets corrected rather than silently depending on the fallback.
        log.error(
            "instagram_tenant_app_secret_stale",
            ig_account_id=ig_account_id,
            detail="Webhook verified via META_APP_SECRET; the app_secret saved on "
                   "the Instagram integration does not match what Meta signs with.",
        )

    for entry in payload.get("entry", []):
        ig_account_id = entry.get("id")
        for messaging_event in entry.get("messaging", []):
            _handle_messaging_event(ig_account_id, messaging_event)
        # T1.1: comment events arrive via entry.changes, not entry.messaging.
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                _handle_comment_event(ig_account_id, change.get("value", {}))

    return {"status": "ok"}


def _handle_messaging_event(ig_account_id: str, event: dict):
    """Route a single messaging event to the right handler."""
    sender_id = event.get("sender", {}).get("id", "")

    if event.get("message", {}).get("is_echo"):
        # An echo is Meta notifying us that the business account sent a
        # message -- via ANY client, including an agent replying directly in
        # the native Instagram app rather than through HAIP. Previously this
        # was discarded entirely, so those replies never appeared in the
        # HAIP inbox even though they'd actually been sent. Store them as
        # outbound messages instead.
        _handle_outbound_echo(ig_account_id, event)
        return

    if "message" in event:
        _handle_inbound_dm(ig_account_id, sender_id, event)
    elif "postback" in event:
        _handle_postback(ig_account_id, sender_id, event)
    elif "story_mention" in event:
        _handle_story_mention(ig_account_id, sender_id, event)


def _handle_inbound_dm(ig_account_id: str, sender_id: str, event: dict):
    """Queue processing for an inbound Instagram DM."""
    message = event.get("message", {})
    mid = message.get("mid", "")

    payload_data = {
        "ig_account_id": ig_account_id,
        "sender_id": sender_id,
        "message_id": mid,
        "text": message.get("text", ""),
        "attachments": message.get("attachments", []),
        "timestamp": event.get("timestamp"),
        "reply_to": message.get("reply_to", {}),
        # T0.3: ad attribution -- present when the DM originated from a
        # Click-to-Instagram ad. Sibling of "message" in the messaging event,
        # not nested inside it.
        "referral": event.get("referral", {}),
    }

    try:
        from app.workers.tasks.process_instagram_dm import process_instagram_dm
        process_instagram_dm.delay(payload_data)
        log.info("instagram_dm_queued", mid=mid, sender=sender_id)
    except Exception as exc:
        log.error("instagram_dm_queue_failed", error=str(exc))


def _handle_outbound_echo(ig_account_id: str, event: dict):
    """Queue processing for a message the business account sent outside HAIP."""
    message = event.get("message", {})
    mid = message.get("mid", "")
    # For an echo, "recipient" is the guest the business account messaged --
    # the roles are reversed relative to an inbound DM.
    recipient_id = event.get("recipient", {}).get("id", "")

    payload_data = {
        "ig_account_id": ig_account_id,
        "recipient_id": recipient_id,
        "message_id": mid,
        "text": message.get("text", ""),
        "attachments": message.get("attachments", []),
        "timestamp": event.get("timestamp"),
    }

    try:
        from app.workers.tasks.process_instagram_dm import process_instagram_echo
        process_instagram_echo.delay(payload_data)
        log.info("instagram_echo_queued", mid=mid, recipient=recipient_id)
    except Exception as exc:
        log.error("instagram_echo_queue_failed", error=str(exc))


def _handle_comment_event(ig_account_id: str, value: dict):
    """
    Queue processing for an inbound Instagram comment.

    T1.1: value shape per Meta's Instagram Platform webhook spec:
      {
        "id": "<comment_id>",
        "text": "...",
        "from": {"id": "<sender_id>", "username": "..."},
        "media": {"id": "<media_id>", "ad_id": "...", "ad_title": "..."},
      }
    """
    from_obj = value.get("from") or {}
    sender_id = from_obj.get("id", "")
    comment_id = value.get("id", "")

    # Guard against self-reply loops -- skip comments posted by the business
    # account itself (e.g. its own reply to an earlier comment), same pattern
    # as the is_echo check for DMs.
    if not sender_id or sender_id == ig_account_id:
        return

    media = value.get("media") or {}
    payload_data = {
        "ig_account_id": ig_account_id,
        "sender_id": sender_id,
        "comment_id": comment_id,
        "text": value.get("text", ""),
        "media_id": media.get("id", ""),
        "media_ad_id": media.get("ad_id", ""),
        "media_ad_title": media.get("ad_title", ""),
        # Meta includes the commenter's username directly in the comment
        # webhook (comments are public content, unlike DM sender profiles,
        # which are consent-gated behind a separate Graph API call --
        # confirmed live that call 500s with IGApiException 230 "User
        # consent is required" for essentially every DM sender). Free,
        # no extra API round trip needed.
        "sender_username": from_obj.get("username", ""),
    }

    try:
        from app.workers.tasks.process_instagram_comment import process_instagram_comment
        process_instagram_comment.delay(payload_data)
        log.info("instagram_comment_queued", comment_id=comment_id, sender=sender_id)
    except Exception as exc:
        log.error("instagram_comment_queue_failed", error=str(exc))


def _handle_postback(ig_account_id: str, sender_id: str, event: dict):
    postback = event.get("postback", {})
    log.info("instagram_postback", sender=sender_id, payload=postback.get("payload"))
    _handle_inbound_dm(ig_account_id, sender_id, {
        **event,
        "message": {
            "mid": f"postback_{event.get('timestamp', '')}",
            "text": postback.get("title", postback.get("payload", "")),
        },
    })


def _handle_story_mention(ig_account_id: str, sender_id: str, event: dict):
    log.info("instagram_story_mention", sender=sender_id)
    _handle_inbound_dm(ig_account_id, sender_id, {
        **event,
        "message": {
            "mid": f"story_{event.get('timestamp', '')}",
            "text": "[Story mention]",
            "attachments": [event.get("story_mention", {})],
        },
    })
