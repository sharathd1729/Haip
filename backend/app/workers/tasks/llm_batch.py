"""Claude Message Batches for nightly jobs (adapters/llm/batch.py; queue ai_scoring, exact-name routes in celery_app.py).

  llm_batch.submit   one job, one tenant: the collect pass, then the batch is created and a poll is queued. Nothing collected,
                     or the batch could not be created = the job runs now with normal calls.
  llm_batch.poll     every POLL_SECONDS until the batch ends (or MAX_WAIT_HOURS: then it is cancelled), then the batch is
                     claimed once (Redis), its results metered at half price, and the job runs again in replay mode:
                     matching calls get the batch answer, every other call runs normally.

JOBS is the list of batchable jobs: job(tenant_id, final, **kwargs). With final=False (collect) it must keep nothing: roll
back, send nothing. Both passes rebuild the prompts from the database, so the job code is the normal code.
"""

from datetime import UTC, datetime, timedelta

import structlog

from app.adapters.llm import batch
from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()


def _lead_outcome_sweep(tenant_id: str, final: bool) -> int:
    from app.services import lead_outcome

    db = SessionLocal()
    done = 0
    try:
        set_tenant_context(db, tenant_id)
        for inquiry, kind in lead_outcome.unconfirmed_closed(db, tenant_id):
            lead_outcome.propose(db, tenant_id, inquiry.id, kind)
            if final:
                db.commit()
                done += 1
            else:
                db.rollback()
                set_tenant_context(db, tenant_id)
        return done
    finally:
        db.rollback()
        db.close()


def _agent_daily_report(tenant_id: str, final: bool, day: str) -> int:
    from app.services import daily_report_service
    from app.workers.tasks.daily_agent_report import _recipients, send_daily_agent_report

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        agent_ids = [a.id for a in _recipients(db, tenant_id) if a.email]
        if not final:
            for agent_id in agent_ids:
                daily_report_service.build_agent_daily_report(db, tenant_id, agent_id, day=day)
            return 0
    finally:
        db.rollback()
        db.close()
    for agent_id in agent_ids:  # inline, so the replay results are seen; the day is pinned at fan-out time
        try:
            send_daily_agent_report(tenant_id, agent_id, day)
        except Exception as exc:  # noqa: BLE001 -- one agent's failure must not skip the rest
            log.warning("llm_batch_agent_report_failed", tenant_id=tenant_id, agent_id=agent_id, error=str(exc)[:300])
    return len(agent_ids)


JOBS = {
    "lead_outcome_sweep": _lead_outcome_sweep,
    "agent_daily_report": _agent_daily_report,
}


def run_final(job: str, tenant_id: str, kwargs: dict, results: dict) -> dict:
    with batch.replaying(results):
        n = JOBS[job](tenant_id, True, **kwargs)
    log.info("llm_batch_job_done", job=job, tenant_id=tenant_id, from_batch=len(results), items=n)
    return {"job": job, "items": n, "from_batch": len(results)}


@celery_app.task(name="llm_batch.submit")
def submit(job: str, tenant_id: str, kwargs: dict | None = None):
    kwargs = kwargs or {}
    if job not in JOBS:
        raise ValueError(f"unknown batch job {job!r}")
    if not batch.claude_on():
        return run_final(job, tenant_id, kwargs, {})
    with batch.collecting(tenant_id) as col:
        JOBS[job](tenant_id, False, **kwargs)
    batch_id = batch.submit(col) if col.requests else None
    if batch_id is None:
        return run_final(job, tenant_id, kwargs, {})
    deadline = (datetime.now(UTC) + timedelta(hours=batch.MAX_WAIT_HOURS)).isoformat()
    metas = {cid: r["meta"] for cid, r in col.requests.items()}
    poll.apply_async((job, tenant_id, kwargs, batch_id, metas, deadline), countdown=batch.POLL_SECONDS)
    return {"job": job, "batch_id": batch_id, "requests": len(metas)}


@celery_app.task(name="llm_batch.poll")
def poll(job: str, tenant_id: str, kwargs: dict, batch_id: str, metas: dict, deadline: str):
    from app.core.cache import idem_check_and_set

    if batch.status(batch_id) != "ended":
        if datetime.now(UTC) < datetime.fromisoformat(deadline):
            poll.apply_async((job, tenant_id, kwargs, batch_id, metas, deadline), countdown=batch.POLL_SECONDS)
            return {"batch_id": batch_id, "status": "processing"}
        batch.cancel(batch_id)
        log.warning("llm_batch_timed_out", job=job, tenant_id=tenant_id, batch_id=batch_id)
        results = {}
    else:
        results = None
    # One replay per batch even if this task is delivered twice (Redis visibility timeout, retry).
    if not idem_check_and_set(f"llm_batch:applied:{batch_id}", ttl=3 * 86400):
        return {"batch_id": batch_id, "status": "already_applied"}
    if results is None:
        results = batch.results(batch_id, tenant_id, metas)
    return run_final(job, tenant_id, kwargs, results)
