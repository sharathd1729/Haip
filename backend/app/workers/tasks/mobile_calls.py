"""Calls app (Android): daily sweep of recordings whose call never arrived (beat "mobile-calls-purge-stale-pending").

A phone's recording can arrive before call_ingest has made its call; it waits in mobile_call_pending and ingest attaches it.
If that ingest failed for good, the row would keep a stranger's audio forever, so rows older than
mobile_device_service.PENDING_MAX_AGE are deleted with their file. One workspace per transaction; files after commit.
"""

import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="mobile_calls.purge_stale_pending")
def purge_stale_pending() -> dict:
    from app.models.tenant import Tenant
    from app.services.media_storage import delete_tenant_objects
    from app.services.mobile_device_service import purge_stale_pending as purge

    db = SessionLocal()
    try:
        tenant_ids = [str(t) for (t,) in db.query(Tenant.id).all()]
    finally:
        db.close()
    files = 0
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            keys = purge(db, tenant_id)
            db.commit()
            if keys:
                files += delete_tenant_objects(tenant_id, keys)
        except Exception as exc:  # noqa: BLE001 -- one workspace failing must not stop the others
            db.rollback()
            log.error("mobile_pending_purge_failed", tenant_id=tenant_id, error=str(exc)[:300])
        finally:
            db.close()
    log.info("mobile_pending_purged", files=files)
    return {"files": files}
