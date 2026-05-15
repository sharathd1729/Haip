"""
Instagram DM webhook receiver.

Meta sends the same webhook format for both WhatsApp and Instagram.
Register this URL in your Meta App → Webhooks → instagram → messages.

Verification:  GET /webhooks/instagram?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
Inbound DMs:   POST /webhooks/instagram  (X-Hub-Signature-256 header)
"""

import hashlib
import hmac
import json
import logging
import os
from fastapi import APIRouter, Request, HTTPException, Query

router = APIRouter(prefix="/webhooks", tags=["webhooks-instagram"])
logger = logging.getLogger(__name__)


def _verify_meta_signature(body: bytes, signature_header: str) -> bool:
    """HMAC-SHA256 verification using META_APP_SECRET."""
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_secret:
        logger.warning("META_APP_SECRET not set — skipping Instagram signature verification")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ── Webhook verification (GET) ────────────────────────────────────────────────

@router.get("/instagram")
def verify_instagram_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    verify_token = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "haip_instagram_verify")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logger.info("Instagram webhook verified")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


# ── Inbound DMs (POST) ────────────────────────────────────────────────────────

@router.post("/instagram")
async def receive_instagram_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_meta_signature(body, sig):
        logger.warning("Invalid Instagram webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Meta wraps entries in {"object": "instagram", "entry": [...]}
    if payload.get("object") != "instagram":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        ig_account_id = entry.get("id")  # Instagram Business Account ID
        for messaging_event in entry.get("messaging", []):
            _handle_messaging_event(ig_account_id, messaging_event)

    return {"status": "ok"}


def _handle_messaging_event(ig_account_id: str, event: dict):
    """Route a single messaging event to the right handler."""
    sender_id = event.get("sender", {}).get("id", "")
    recipient_id = event.get("recipient", {}).get("id", "")

    # Skip echo (messages sent by the page itself)
    if event.get("message", {}).get("is_echo"):
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
    }

    try:
        from app.workers.tasks.process_instagram_dm import process_instagram_dm
        process_instagram_dm.delay(payload_data)
        logger.info("Queued Instagram DM mid=%s from sender=%s", mid, sender_id)
    except Exception as exc:
        logger.error("Failed to queue Instagram DM: %s", exc)


def _handle_postback(ig_account_id: str, sender_id: str, event: dict):
    """Handle quick-reply postbacks (user tapped a button)."""
    postback = event.get("postback", {})
    logger.info(
        "Instagram postback from %s: payload=%s title=%s",
        sender_id, postback.get("payload"), postback.get("title"),
    )
    # Queue as a regular text message using the postback title
    _handle_inbound_dm(ig_account_id, sender_id, {
        **event,
        "message": {
            "mid": f"postback_{event.get('timestamp', '')}",
            "text": postback.get("title", postback.get("payload", "")),
        },
    })


def _handle_story_mention(ig_account_id: str, sender_id: str, event: dict):
    """User mentioned the business account in a story — log and potentially respond."""
    logger.info("Instagram story mention from %s on account %s", sender_id, ig_account_id)
    # Treat as a lead — queue with empty text so agent can follow up
    _handle_inbound_dm(ig_account_id, sender_id, {
        **event,
        "message": {
            "mid": f"story_{event.get('timestamp', '')}",
            "text": "[Story mention]",
            "attachments": [event.get("story_mention", {})],
        },
    })
