"""Acefone IVR webhook."""
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


@router.post("/acefone/{tenant_slug}")
async def acefone_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
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
