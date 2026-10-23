"""Why a lead was won / lost: the AI's proposal (lead_outcome.py; queue ai_scoring, exact-name routes in celery_app.py).

  lead_outcome.propose            one lead, one kind (won | lost). Queued when a person opens the Won / Lost dialog
                                  (POST /leads/{id}/outcome/propose); the dialog polls GET /leads/{id}/outcome.
  lead_outcome.sweep_all_tenants  nightly beat (02:35 IST): leads closed without a reason and without a proposal, at most
                                  40 per workspace. One transaction per lead, per tenant.

The LLM is only ever called here, in a worker -- never in a request handler. A proposal never sets the reason itself.
"""
import structlog

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="lead_outcome.propose", bind=True, max_retries=1, default_retry_delay=60)
def propose(self, inquiry_id: str, tenant_id: str, kind: str):
    from app.core.database import set_tenant_context
    from app.services import lead_outcome

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        out = lead_outcome.propose(db, tenant_id, inquiry_id, kind)
        db.commit()
        return {"status": (out or {}).get("status")}
    except Exception as exc:
        db.rollback()
        log.warning("lead_outcome_propose_failed", tenant_id=tenant_id, inquiry_id=inquiry_id, error=str(exc)[:300])
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="lead_outcome.sweep_all_tenants")
def sweep_all_tenants():
    from app.core.database import set_tenant_context
    from app.models.tenant import Tenant
    from app.services import lead_outcome

    db = SessionLocal()
    done = 0
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
        db.commit()
        for tenant_id in tenant_ids:
            try:
                set_tenant_context(db, tenant_id)
                for inquiry, kind in lead_outcome.unconfirmed_closed(db, tenant_id):
                    lead_outcome.propose(db, tenant_id, inquiry.id, kind)
                    db.commit()
                    done += 1
            except Exception as exc:          # one tenant's failure must not skip the rest
                db.rollback()
                log.warning("lead_outcome_sweep_tenant_failed", tenant_id=tenant_id, error=str(exc)[:300])
        log.info("lead_outcome_sweep_done", proposals=done)
        return {"proposals": done}
    finally:
        db.close()
