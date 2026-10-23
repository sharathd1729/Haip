"""The learning loop's Celery tasks (exact-name routes to queue ``ai_scoring``).

  learning.evaluate_all       beat daily 07:15 IST: one learning.evaluate_tenant per workspace with a running experiment
  learning.evaluate_tenant    evaluate every running experiment (keep / roll back / stop / continue), one transaction
  learning.start_experiment   the bench gate + start for an approved or "act" proposal (never inside a request); runs the
                              bench in a throwaway in-memory database (learning.bench_gate), prefork workers only

Never retried automatically: a decision is idempotent on the next run (a decided experiment is no longer "running").
"""
from __future__ import annotations

from typing import Optional

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="learning.evaluate_tenant")
def evaluate_tenant(tenant_id: str) -> dict:
    from app.services.learning import experiments
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        out = experiments.evaluate_tenant(db, tenant)
        db.commit()
        return {"status": "ok", "decisions": [d["result"] for d in out]}
    except Exception:
        db.rollback()
        log.exception("learning_evaluate_failed", tenant_id=tenant_id)
        raise
    finally:
        db.close()


@shared_task(name="learning.evaluate_all")
def evaluate_all() -> dict:
    from app.models.analyst import AgentExperiment
    db = SessionLocal()
    try:
        ids = [r[0] for r in db.query(AgentExperiment.tenant_id).filter_by(status="running").distinct().all()]
    finally:
        db.close()
    for tid in ids:
        evaluate_tenant.delay(tid)
    return {"tenants_queued": len(ids)}


@shared_task(name="learning.start_experiment")
def start_experiment(tenant_id: str, experiment_id: str, actor_id: Optional[str] = None) -> dict:
    from app.services.learning import experiments
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        exp = experiments.get(db, tenant_id, experiment_id) if tenant else None
        if exp is None or exp.status not in ("proposed", "awaiting_approval"):
            return {"status": "skipped"}
        experiments.start(db, tenant, exp, actor_id=actor_id)
        db.commit()
        return {"status": exp.status}
    except Exception:
        db.rollback()
        log.exception("learning_start_failed", tenant_id=tenant_id, experiment_id=experiment_id)
        raise
    finally:
        db.close()
