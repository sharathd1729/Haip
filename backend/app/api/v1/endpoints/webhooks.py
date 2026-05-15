"""
Inbound webhook endpoints for IVR providers and WhatsApp.
All endpoints verify signatures before queuing work.
"""
import json
import hashlib
import hmac
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from fastapi import Depends
from app.core.database import get_db
from app.core.config import settings
from app.adapters.ivr import get_ivr_adapter
from app.models.tenant import Tenant
from app.workers.tasks.call_ingest import ingest_call
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/ivr/callerdesk/{tenant_slug}")
async def callerdesk_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    """CallerDesk call-completed webhook."""
    body = await request.body()
    headers = dict(request.headers)

    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    adapter = get_ivr_adapter("callerdesk")
    if not adapter.verify_webhook_signature(body, headers):
        log.warning("callerdesk_webhook_signature_invalid", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    log.info("callerdesk_webhook_received", tenant=tenant_slug, call_id=payload.get("call_id"))

    # Queue async processing (return 200 immediately to IVR provider)
    ingest_call.delay(
        payload=payload,
        tenant_id=tenant.id,
        ivr_provider="callerdesk",
    )

    return {"status": "queued"}


@router.post("/ivr/acefone/{tenant_slug}")
async def acefone_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    """Acefone call-completed webhook."""
    body = await request.body()
    headers = dict(request.headers)

    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    adapter = get_ivr_adapter("acefone")
    if not adapter.verify_webhook_signature(body, headers):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    ingest_call.delay(payload=payload, tenant_id=tenant.id, ivr_provider="acefone")
    return {"status": "queued"}


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
):
    """Meta webhook verification (GET)."""
    if hub_mode == "subscribe" and hub_verify_token == settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """Meta WhatsApp Cloud API inbound message webhook."""
    body = await request.body()
    headers = dict(request.headers)

    # Verify Meta signature
    if not _verify_meta_signature(body, headers):
        raise HTTPException(status_code=401, detail="Invalid Meta signature")

    payload = json.loads(body)
    log.info("whatsapp_webhook_received")

    from app.workers.tasks.whatsapp import process_whatsapp_message
    process_whatsapp_message.delay(payload=payload)

    return {"status": "queued"}


def _verify_meta_signature(body: bytes, headers: dict) -> bool:
    if not settings.META_APP_SECRET:
        return True  # Skip in dev

    signature = headers.get("x-hub-signature-256", "")
    if not signature.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        settings.META_APP_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
