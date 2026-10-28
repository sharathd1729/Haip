"""GPS push webhook: POST /api/v1/webhooks/gps/{tenant_slug} (format and signing: adapters/gps/webhook.py).

Rate-limited with the other /api/v1/webhooks/ paths. Checks only what must answer 401/413/422 (business, signature, time
window, body shape), then queues gps.ingest and answers 200 at once: storing fixes and checking trip rules run in Celery.
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.adapters import gps as adapters
from app.adapters.gps import webhook
from app.core.database import get_db, set_tenant_context
from app.models.tenant import Tenant
from app.services import gps_ingest, gps_service

log = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks-gps"])


@router.post("/gps/{tenant_slug}")
async def gps_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if len(body) > webhook.MAX_BODY:
        raise HTTPException(status_code=413, detail="Body is larger than 512 KB.")
    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    set_tenant_context(db, tenant.id)
    now = datetime.now(UTC)
    try:
        positions = adapters.parse_push(
            adapters.PROVIDERS["webhook"],
            body,
            dict(request.headers),
            gps_service.webhook_secret(db, tenant.id),
            now=now,
        )
    except adapters.GpsAuthError as exc:
        log.warning("gps_webhook_refused", tenant_slug=tenant_slug, reason=str(exc))
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except adapters.GpsPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if positions:
        from app.workers.tasks.gps import ingest

        ingest.delay(tenant.id, "webhook", [gps_ingest.to_dict(p) for p in positions])
    return {"status": "queued", "accepted": len(positions)}
