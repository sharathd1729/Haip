"""tasks `channex.sync_all_tenants` (beat every 15 min) and `channex.sync_tenant` (one workspace, also POST /channex/sync):
pull Channex's booking feed into HAIP, then push HAIP's availability (and rates where switched on) for every mapped unit
(services/channex_service.py). Only workspaces with an active "channex" integration. One workspace per transaction;
a failure in one never stops the others.
"""

import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="channex.sync_tenant")
def sync_tenant(tenant_id: str) -> dict:
    from app.adapters.pms.channex import ChannexError
    from app.services import channex_service as svc

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        try:
            client = svc.client_for(db, tenant_id)
        except (svc.NotConnected, ChannexError) as exc:
            return {"tenant_id": tenant_id, "status": "not_connected", "detail": str(exc)}
        try:
            pulled = svc.pull_tenant(db, tenant_id, client=client)
            pushed = svc.push_tenant(db, tenant_id, client=client)
        except ChannexError as exc:
            log.error("channex_sync_failed", tenant_id=tenant_id, error=str(exc))
            return {"tenant_id": tenant_id, "status": "failed", "detail": str(exc)}
        finally:
            client.close()
        return {"tenant_id": tenant_id, "status": "ok", "pulled": pulled,
                "pushed": {k: v for k, v in pushed.items() if k != "warnings"}, "warnings": len(pushed["warnings"])}
    finally:
        db.close()


@celery_app.task(name="channex.sync_all_tenants")
def sync_all_tenants() -> dict:
    from app.models.integration import Integration

    db = SessionLocal()
    try:
        ids = [t for (t,) in db.query(Integration.tenant_id).filter_by(kind="channex", status="active").all()]
    finally:
        db.close()
    for tid in ids:
        sync_tenant.delay(tid)
    return {"tenants_queued": len(ids)}
