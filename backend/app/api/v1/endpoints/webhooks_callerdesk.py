"""CallerDesk IVR webhook."""
import json
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.adapters.ivr import get_ivr_adapter
from app.models.tenant import Tenant
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

    adapter = get_ivr_adapter("callerdesk")
    if not adapter.verify_webhook_signature(body, headers):
        log.warning("callerdesk_sig_invalid", tenant=tenant_slug)
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    log.info("callerdesk_webhook_received", tenant=tenant_slug, call_id=payload.get("call_id"))
    ingest_call.delay(payload=payload, tenant_id=tenant.id, ivr_provider="callerdesk")
    return {"status": "queued"}
