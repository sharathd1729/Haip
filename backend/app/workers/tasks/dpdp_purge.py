"""
DPDP erasure job (daily 02:00 IST, beat "dpdp-purge-daily", task "tasks.dpdp_purge", queue call_ingest).

Fulfils right-to-erasure requests whose 30-day grace period has passed (dpdp_erasure_service): everything HAIP holds about
the guest is erased, one workspace per transaction (an audit chain is per tenant), each request on its own savepoint so one
failure never blocks the others, then the stored files (recordings, media) are deleted. Also removes revoked login refresh
tokens older than 90 days.

Off until the owner switches it on: with DPDP_ERASURE_ENABLED false (the default) it only REPORTS -- how many requests are
pending and due per workspace, and how many old revoked tokens there are -- and writes nothing. Before switching it on, run
scripts/dpdp_erasure_report.py on production to see exactly what the first run will erase.
"""
from datetime import datetime, timedelta, timezone

import structlog

from app.core.config import settings
from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()

TOKEN_PURGE_DAYS = 90    # revoked refresh tokens are removed after 90 days


@celery_app.task(name="tasks.dpdp_purge")
def dpdp_purge() -> dict:
    from app.models.tenant import Tenant
    from app.models.user import RefreshToken
    from app.services import dpdp_erasure_service as erasure

    apply = bool(getattr(settings, "DPDP_ERASURE_ENABLED", False))
    stats: dict = {"applied": apply, "tenants": {}, "tokens": 0}
    db = SessionLocal()
    try:
        tenant_ids = [t for (t,) in db.query(Tenant.id).all()]
    finally:
        db.close()

    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, str(tenant_id))
            out = erasure.run_tenant(db, str(tenant_id), apply=apply)
            if out["pending"]:
                stats["tenants"][str(tenant_id)] = {k: out[k] for k in ("pending", "due", "erased", "failed", "files")}
        except Exception as exc:  # noqa: BLE001 -- one workspace failing must not stop the others
            db.rollback()
            log.error("dpdp_erasure_tenant_failed", tenant_id=tenant_id, error=str(exc)[:300])
        finally:
            db.close()

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=TOKEN_PURGE_DAYS)
        q = db.query(RefreshToken).filter(RefreshToken.is_revoked.is_(True), RefreshToken.created_at <= cutoff.isoformat())
        if apply:
            stats["tokens"] = q.delete(synchronize_session=False)
            db.commit()
        else:
            stats["tokens"] = q.count()
    finally:
        db.close()

    due = sum(t["due"] for t in stats["tenants"].values())
    if apply:
        log.info("dpdp_erasure_run", **{k: v for k, v in stats.items() if k != "tenants"},
                 erased=sum(t["erased"] for t in stats["tenants"].values()), due=due)
    elif due:
        log.warning("dpdp_erasure_due_but_disabled", due=due, tenants=len(stats["tenants"]),
                    hint="set DPDP_ERASURE_ENABLED=true after checking scripts/dpdp_erasure_report.py")
    return stats
