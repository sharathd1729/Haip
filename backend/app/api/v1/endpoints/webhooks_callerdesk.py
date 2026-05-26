"""CallerDesk IVR webhook."""
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


@router.post("/callerdesk/{tenant_slug}")
async def callerdesk_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    headers = dict(request.headers)

    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Per-tenant webhook secret stored in the Integration credentials blob.
    # Never use a global env-var secret shared across all tenants.
    integration = db.query(Integration).filter_by(
        tenant_id=tenant.id, kind="callerdesk"
    ).first()
    if not integration or not integration.credentials_kms_blob:
        log.warning("callerdesk_integration_not_configured", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="CallerDesk integration not configured for this tenant")

    tenant_secret = get_credential(integration.credentials_kms_blob, "webhook_secret")
    if not tenant_secret:
        log.warning("callerdesk_webhook_secret_missing", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Webhook secret not configured — update the CallerDesk integration")

    adapter = get_ivr_adapter("callerdesk")
    if not adapter.verify_webhook_signature(body, headers, secret=tenant_secret):
        log.warning("callerdesk_sig_invalid", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    log.info("callerdesk_webhook_received", tenant=tenant_slug, call_id=payload.get("call_id"))
    ingest_call.delay(payload=payload, tenant_id=tenant.id, ivr_provider="callerdesk")
    return {"status": "queued"}
