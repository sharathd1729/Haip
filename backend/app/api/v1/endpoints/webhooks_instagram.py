"""
Instagram DM webhook receiver.

Meta sends the same webhook format for both WhatsApp and Instagram.
Register this URL in your Meta App → Webhooks → instagram → messages.

Verification:  GET /webhooks/instagram?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
Inbound DMs:   POST /webhooks/instagram  (X-Hub-Signature-256 header)
"""

import json
from secrets import compare_digest
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from app.core.config import settings
from app.core.webhook_security import verify_meta_signature
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks-instagram"])


# ── Webhook verification (GET) ────────────────────────────────────────────────

@router.get("/instagram")
def verify_instagram_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    verify_token = settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN
    if (
        hub_mode == "subscribe"
        and verify_token
        and compare_digest(hub_verify_token, verify_token)
    ):
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

    # Resolve app_secret from the tenant integration matching this IG account,
    # falling back to the global env var only if no per-tenant secret is found.
    app_secret = ""
    entries = payload.get("entry", [])
    ig_account_id = entries[0].get("id") if entries else None

    if ig_account_id:
        try:
            from app.core.database import SessionLocal
            from app.models.integration import Integration
            from app.core.encryption import decrypt_credentials
            _db = SessionLocal()
            try:
                _candidates = (
                    _db.query(Integration)
                    .filter(Integration.kind == "instagram", Integration.status == "active")
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

    if not app_secret:
        app_secret = settings.META_APP_SECRET

    # Raises 401 on failure; in dev with no secret logs a warning and continues
    verify_meta_signature(
        body=body,
        signature_header=sig,
        env=settings.ENVIRONMENT,
        secret=app_secret,
    )

    for entry in payload.get("entry", []):
        ig_account_id = entry.get("id")
        for messaging_event in entry.get("messaging", []):
            _handle_messaging_event(ig_account_id, messaging_event)

    return {"status": "ok"}


def _handle_messaging_event(ig_account_id: str, event: dict):
    """Route a single messaging event to the right handler."""
    sender_id = event.get("sender", {}).get("id", "")

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
