"""Every 5 minutes: hand out leads that waited for working hours or for an
available agent, and pass on leads their owner never contacted -- per each
tenant's Settings > Lead assignment rules. See
app/services/lead_assignment_service.py."""
import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="lead_assignment.tick")
def tick() -> dict:
    from app.services import lead_assignment_service as svc

    totals = {"tenants": 0, "assigned": 0, "reassigned": 0}
    db = SessionLocal()
    try:
        tenant_ids = [
            t.id for t in db.query(Tenant.id).filter(Tenant.lead_assignment_config.isnot(None)).all()
        ]
    finally:
        db.close()

    for tid in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tid)
            tenant = db.query(Tenant).filter_by(id=tid).first()
            if not tenant:
                continue
            cfg = svc.get_config(tenant)
            if cfg.mode == "manual" and not cfg.reassign_if_not_contacted:
                continue
            res = svc.run_tick(db, tenant)
            totals["tenants"] += 1
            totals["assigned"] += res["assigned"]
            totals["reassigned"] += res["reassigned"]
        except Exception as exc:  # one tenant's failure must not stop the rest
            db.rollback()
            log.error("lead_assignment_tick_failed", tenant_id=tid, error=str(exc))
        finally:
            db.close()
    return totals
