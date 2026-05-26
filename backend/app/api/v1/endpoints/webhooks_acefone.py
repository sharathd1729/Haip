"""Acefone IVR webhook."""
import json
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


@router.post("/acefone/{tenant_slug}")
async def acefone_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    headers = dict(request.headers)

    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Per-tenant webhook secret stored in the Integration credentials blob.
    integration = db.query(Integration).filter_by(
        tenant_id=tenant.id, kind="acefone"
    ).first()
    if not integration or not integration.credentials_kms_blob:
        log.warning("acefone_integration_not_configured", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Acefone integration not configured for this tenant")

    tenant_secret = get_credential(integration.credentials_kms_blob, "webhook_secret")
    if not tenant_secret:
        log.warning("acefone_webhook_secret_missing", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Webhook secret not configured — update the Acefone integration")

    adapter = get_ivr_adapter("acefone")
    if not adapter.verify_webhook_signature(body, headers, secret=tenant_secret):
        log.warning("acefone_sig_invalid", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    log.info("acefone_webhook_received", tenant=tenant_slug)
    ingest_call.delay(payload=payload, tenant_id=tenant.id, ivr_provider="acefone")
    return {"status": "queued"}
