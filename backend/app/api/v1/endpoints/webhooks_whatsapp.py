"""Meta WhatsApp Cloud API webhook."""
import json
from fastapi import APIRouter, Request, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.core.webhook_security import verify_meta_signature
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
    sig = request.headers.get("X-Hub-Signature-256", "")

    # Raises 401 on failure; in dev with no secret logs a warning and continues
    verify_meta_signature(
        body=body,
        signature_header=sig,
        env=settings.ENVIRONMENT,
        secret=settings.META_APP_SECRET,
    )

    payload = json.loads(body)
    log.info("whatsapp_webhook_received")
    process_whatsapp_message.delay(payload=payload)
    return {"status": "queued"}
