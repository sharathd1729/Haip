"""Lead autopilot Celery tasks (queue ai_scoring, exact-name routes in celery_app.py).

  lead_autopilot.evaluate_inquiry   one lead, rules then the AI classifier. Queued by wrap_up (after a call is analysed)
                                    and by generate_ai_summary (after the summary refresh, which is already debounced for
                                    message bursts -- so a burst of guest messages costs one evaluation, not one each).
  lead_autopilot.sweep_all_tenants  daily beat, rules only (dates passed, unanswered calls, silence, bookings).

The LLM is only ever called here, in a worker -- never in a request handler.
"""
import structlog

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="lead_autopilot.evaluate_inquiry", bind=True, max_retries=1, default_retry_delay=120)
def evaluate_inquiry(self, inquiry_id: str, tenant_id: str, trigger: str = "event"):
    from app.core.database import set_tenant_context
    from app.services import lead_autopilot_service

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        event = lead_autopilot_service.evaluate(db, tenant_id, inquiry_id, allow_ai=trigger != "sweep")
        db.commit()
        if event is not None:
            log.info("lead_autopilot_evaluated", tenant_id=tenant_id, inquiry_id=inquiry_id, trigger=trigger,
                     rule=event.rule, status=event.status)
    except Exception as exc:
        db.rollback()
        log.warning("lead_autopilot_evaluate_failed", tenant_id=tenant_id, inquiry_id=inquiry_id, error=str(exc)[:300])
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="lead_autopilot.sweep_all_tenants")
def sweep_all_tenants():
    """One transaction per lead, per tenant (a transaction never audits two tenants)."""
    from app.models.tenant import Tenant
    from app.services import lead_autopilot_service

    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
        db.commit()
        for tenant_id in tenant_ids:
            try:
                n = lead_autopilot_service.sweep_tenant(db, tenant_id)
                if n:
                    log.info("lead_autopilot_sweep_done", tenant_id=tenant_id, decisions=n)
            except Exception as exc:          # one tenant's failure must not skip the rest
                db.rollback()
                log.warning("lead_autopilot_sweep_tenant_failed", tenant_id=tenant_id, error=str(exc)[:300])
    finally:
        db.close()
