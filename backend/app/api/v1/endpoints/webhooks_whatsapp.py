"""Meta WhatsApp Cloud API webhook."""
import json
from secrets import compare_digest
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.core.config import settings
from app.core.webhook_security import verify_meta_signature
from app.core.encryption import decrypt_credentials
from app.workers.tasks.whatsapp import process_whatsapp_message, resolve_wa_tenant
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
):
    verify_token = settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN
    if (
        hub_mode == "subscribe"
        and verify_token  # must be configured — empty token always rejects
        and compare_digest(hub_verify_token, verify_token)
    ):
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    T1.1: verified against the specific tenant's own app_secret (stored
    encrypted on Integration.credentials_kms_blob at connect-key time --
    integrations.py already accepts and stores it, it just wasn't being
    read back here). Each tenant is assumed to run its own Meta App (per
    your confirmation) -- Meta signs X-Hub-Signature-256 with the App
    Secret, which is inherently app-scoped, not per-WABA, so this only
    works if tenants don't share a Meta App. A tenant with no app_secret
    configured is rejected outright (401), no shared/global fallback --
    unlike Instagram's webhook, which still falls back to
    settings.META_APP_SECRET (a pre-existing inconsistency, not fixed
    here; out of scope for the WhatsApp module).
    """
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    try:
        payload_peek = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    phone_number_id = ""
    for entry in payload_peek.get("entry", []):
        for change in entry.get("changes", []):
            phone_number_id = change.get("value", {}).get("metadata", {}).get("phone_number_id", "")
            if phone_number_id:
                break
        if phone_number_id:
            break

    db: Session = SessionLocal()
    try:
        tenant = resolve_wa_tenant(db, phone_number_id)
        if not tenant:
            log.warning("whatsapp_webhook_tenant_not_found", phone_number_id=phone_number_id)
            raise HTTPException(status_code=404, detail="Tenant not found for this WhatsApp number")

        app_secret = ""
        from app.models.integration import Integration
        integration = db.query(Integration).filter(
            Integration.tenant_id == tenant.id,
            Integration.kind.in_(["whatsapp_meta", "whatsapp"]),
            Integration.status == "active",
        ).first()
        if integration and integration.credentials_kms_blob:
            try:
                creds = decrypt_credentials(integration.credentials_kms_blob)
                app_secret = creds.get("app_secret", "")
            except Exception as exc:
                log.warning("whatsapp_webhook_secret_decrypt_failed", tenant_id=tenant.id, error=str(exc))

        if not app_secret:
            log.warning("whatsapp_webhook_secret_missing", tenant_id=tenant.id)
            raise HTTPException(status_code=401, detail="WhatsApp webhook secret not configured for this tenant")

        verify_meta_signature(
            body=body,
            signature_header=sig,
            env=settings.ENVIRONMENT,
            secret=app_secret,
        )
    finally:
        db.close()

    log.info("whatsapp_webhook_received", tenant_id=tenant.id)
    process_whatsapp_message.delay(payload=payload_peek)
    return {"status": "queued"}
