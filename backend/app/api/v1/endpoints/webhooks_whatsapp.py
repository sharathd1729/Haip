"""Meta WhatsApp Cloud API webhook."""
import json
import hashlib
import hmac
from fastapi import APIRouter, Request, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.workers.tasks.whatsapp import process_whatsapp_message
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    body = await request.body()
    headers = dict(request.headers)

    if not _verify_meta_signature(body, headers):
        raise HTTPException(status_code=401, detail="Invalid Meta signature")

    payload = json.loads(body)
    log.info("whatsapp_webhook_received")
    process_whatsapp_message.delay(payload=payload)
    return {"status": "queued"}


def _verify_meta_signature(body: bytes, headers: dict) -> bool:
    if not settings.META_APP_SECRET:
        return True
    sig = headers.get("x-hub-signature-256", "")
    if not sig.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.META_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected)
