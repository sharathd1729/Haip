"""Calls app (Android) sweeps.

mobile_calls.requeue_stuck (beat "mobile-calls-requeue-stuck", every 15 min): a phone call queued into call_ingest whose task
never made the call (broker down, worker lost) is queued again from the payload kept on its waiting row.

mobile_calls.purge_stale_pending (beat "mobile-calls-purge-stale-pending", daily): recordings whose call never arrived.

A phone's recording can arrive before call_ingest has made its call; it waits in mobile_call_pending and ingest attaches it.
If that ingest failed for good, the row would keep a stranger's audio forever, so rows older than
mobile_device_service.PENDING_MAX_AGE are deleted with their file. One workspace per transaction; files after commit.
"""

from datetime import UTC, datetime, timedelta

import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.models.call import Call
from app.models.mobile_device import MobileCallPending
from app.workers.celery_app import celery_app

log = structlog.get_logger()

REQUEUE_AFTER = timedelta(minutes=15)  # ingest normally makes the call within seconds
MAX_REQUEUES = 5


def requeue_stuck(db, tenant_id: str, send, now: datetime | None = None, limit: int = 200) -> int:
    """Queue again (send(payload)) each phone call this workspace queued more than REQUEUE_AFTER ago whose call_ingest task
    never made the call, at most MAX_REQUEUES times, REQUEUE_AFTER apart. An attempt counts only once send() succeeded:
    with the broker still down it stops and the next run tries again. The caller commits. Returns how many were sent."""
    now = now or datetime.now(UTC)
    rows = (
        db.query(MobileCallPending)
        .filter(
            MobileCallPending.tenant_id == tenant_id,
            MobileCallPending.payload.isnot(None),
            MobileCallPending.requeue_attempts < MAX_REQUEUES,
            MobileCallPending.updated_at < now - REQUEUE_AFTER,
        )
        .order_by(MobileCallPending.created_at)
        .limit(limit)
        .all()
    )
    if not rows:
        return 0
    made = {
        r[0]
        for r in db.query(Call.ivr_call_id)
        .filter(Call.tenant_id == tenant_id, Call.ivr_call_id.in_([r.ivr_call_id for r in rows]))
        .all()
    }
    sent = 0
    for row in rows:
        if row.ivr_call_id in made:
            continue  # ingest made the call; its own link_pending clears the row
        try:
            send(row.payload)
        except Exception as exc:  # noqa: BLE001 -- broker still down: not an attempt, the next run retries
            log.error("mobile_call_requeue_send_failed", tenant_id=tenant_id, error=str(exc)[:200])
            break
        row.requeue_attempts = (row.requeue_attempts or 0) + 1
        row.updated_at = now  # spaces the next attempt REQUEUE_AFTER from this one
        sent += 1
    if sent:
        log.warning("mobile_calls_requeued", tenant_id=tenant_id, count=sent)
    return sent


@celery_app.task(name="mobile_calls.requeue_stuck")
def requeue_stuck_all() -> dict:
    from app.models.tenant import Tenant
    from app.services.mobile_device_service import PROVIDER
    from app.workers.tasks.call_ingest import ingest_call

    db = SessionLocal()
    try:
        tenant_ids = [str(t) for (t,) in db.query(Tenant.id).all()]
    finally:
        db.close()
    total = 0
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            total += requeue_stuck(db, tenant_id, lambda p, t=tenant_id: ingest_call.delay(p, t, PROVIDER))
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- one workspace failing must not stop the others
            db.rollback()
            log.error("mobile_call_requeue_failed", tenant_id=tenant_id, error=str(exc)[:300])
        finally:
            db.close()
    return {"requeued": total}


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
