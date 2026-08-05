"""Mcube IVR webhook."""
import json
import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.adapters.ivr import get_ivr_adapter
from app.models.tenant import Tenant
from app.models.integration import Integration
from app.core.encryption import get_credential
from app.workers.tasks.call_ingest import ingest_call
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/mcube/{tenant_slug}/{url_secret}")
async def mcube_webhook(tenant_slug: str, url_secret: str, request: Request, db: Session = Depends(get_db)):
    """
    Mcube documents no request-signing/shared-secret scheme (unlike
    CallerDesk/Acefone's HMAC signatures) -- authentication instead relies
    on an unguessable per-tenant secret embedded directly in the webhook
    URL path, which is what's registered in Mcube's dashboard. Verified
    with a constant-time comparison, same webhook_secret field the
    connect-key flow already collects for every IVR provider.
    """
    body = await request.body()

    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    integration = db.query(Integration).filter_by(
        tenant_id=tenant.id, kind="mcube"
    ).first()
    if not integration or not integration.credentials_kms_blob:
        log.warning("mcube_integration_not_configured", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Mcube integration not configured for this tenant")
    if integration.status != "active":
        # Deliberately disconnected (e.g. Ratha moved to Vobiz-only) -- the
        # Integration row and any past Call rows stay in the DB, but new
        # webhook posts are rejected even if Mcube's own dashboard is still
        # pointed at this URL.
        log.warning("mcube_integration_disconnected", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Mcube integration is disconnected for this tenant")

    tenant_secret = get_credential(integration.credentials_kms_blob, "webhook_secret")
    if not tenant_secret or not secrets.compare_digest(url_secret, tenant_secret):
        log.warning("mcube_url_secret_invalid", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # verify_webhook_signature() is a documented no-op for this provider
    # (see McubeAdapter) -- the URL-path secret check above IS the auth.
    adapter = get_ivr_adapter("mcube")
    if not adapter.verify_webhook_signature(body, dict(request.headers)):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    log.info("mcube_webhook_received", tenant=tenant_slug, call_id=payload.get("callid"))
    ingest_call.delay(payload=payload, tenant_id=tenant.id, ivr_provider="mcube")
    return {"status": "queued"}
