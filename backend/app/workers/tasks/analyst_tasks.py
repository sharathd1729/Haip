"""The AI business analyst's Celery tasks (all exact-name routes to queue ``ai_scoring``: they may call the LLM router).

  analyst.tick              beat every 15 min: for each workspace with ``brand_config.analyst.enabled``, queue the kinds whose
                            local time has passed and whose period has no report yet (analyst.settings.is_due)
  analyst.run_report        compute facts, write the brief (router ``analyst_brief``, fallback deterministic), propose changes,
                            then deliver (email / WhatsApp when switched on)
  analyst.answer_followup   answer one "ask a follow-up" question from the report's facts (Ask HAIP summary route)
  analyst.ask_haip          answer one free-form Ask HAIP question (POST /analyst/ask-haip, services/analyst/ask_haip_jobs)

Never retried automatically: a run that already e-mailed people must not e-mail them twice; the next tick or a manual run
picks up anything left.
"""
from __future__ import annotations

from typing import Optional

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.adapters.llm.scope import scoped_task

log = structlog.get_logger()


@shared_task(name="analyst.run_report")
@scoped_task("analyst", prompt_key="analyst_brief")
def run_report(tenant_id: str, kind: str, actor_id: Optional[str] = None, force: bool = False, deliver: bool = True) -> dict:
    from app.services.analyst import delivery, reports
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        row = reports.generate(db, tenant, kind, actor_id=actor_id, force=force)
        # Scheduled runs deliver once per report; a manual re-run (force) only recomputes, it never e-mails people again.
        if deliver and not force and not (row.delivery or {}).get("at"):
            delivery.deliver(db, tenant, row)
        return {"status": "ok", "report_id": row.id, "source": row.brief_source}
    except Exception:
        db.rollback()
        log.exception("analyst_run_failed", tenant_id=tenant_id, kind=kind)
        raise
    finally:
        db.close()


@shared_task(name="analyst.answer_followup")
@scoped_task("analyst", ref_type="analyst_report", ref_arg="report_id", prompt_key="analyst_followup")
def answer_followup(tenant_id: str, report_id: str, followup_id: str) -> dict:
    from app.services.analyst import ask, reports
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        r = reports.get(db, tenant_id, report_id)
        if r is None:
            return {"status": "no_report"}
        return ask.answer(db, r, followup_id)
    finally:
        db.close()


@shared_task(name="analyst.ask_haip")
@scoped_task("ask_haip", prompt_key="ask_haip_freeform_sql")
def ask_haip(tenant_id: str, job_id: str, user_id: str) -> dict:
    """Answer one Ask HAIP question (POST /analyst/ask-haip) with the free-form analyst and store it on the job."""
    import asyncio

    from app.services.analyst import ask_haip_jobs as jobs
    from app.services.ask_haip_freeform_service import answer_freeform_question

    job = jobs.get(tenant_id, job_id)
    if not job or job.get("status") != "pending":
        return {"status": "skipped"}
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        try:
            out = asyncio.run(answer_freeform_question(db=db, tenant_id=tenant_id, user_id=user_id, question=job["question"]))
        except Exception as exc:  # noqa: BLE001 -- the owner sees a plain failure and can ask again
            log.error("ask_haip_job_failed", tenant_id=tenant_id, error=str(exc)[:300])
            out = {}
        result = jobs.result_of(job["question"], out)
        jobs.finish(tenant_id, job_id, result)
        return {"status": result["status"]}
    finally:
        db.close()


@shared_task(name="analyst.tick")
def tick() -> dict:
    from app.models.analyst import AnalystReport
    from app.services.analyst import settings as s
    from app.services.analyst.periods import local_now, windows
    local = local_now()
    queued = 0
    db = SessionLocal()
    try:
        for tenant in db.query(Tenant).all():
            cfg = s.get(tenant)
            if not cfg.enabled:
                continue
            for kind in s.SCHEDULE_FIELD:
                if not s.is_due(cfg, kind, local):
                    continue
                start = windows(kind, local.date())[0].d_from
                if db.query(AnalystReport.id).filter_by(tenant_id=tenant.id, kind=kind, period_start=start).first():
                    continue
                run_report.delay(tenant.id, kind)
                queued += 1
    finally:
        db.close()
    return {"queued": queued}
