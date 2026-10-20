"""The Manager: one weekly agency run per workspace (plan 18 Oct 2026, phase A).

Steps, each logged as a marketing_tasks row under one run_id, each gated by its role's autonomy level:
  research -> fresh audit (measured snapshot + AI reading)
  strategy -> plan for the next 7 days (uses the audit)
  copy     -> one draft per calendar entry (max MAX_DRAFTS), AI-written
  design   -> an AI image request per drafted post/promo, only if AI images are on and under the monthly cap
  submit   -> drafts go to "waiting for approval"; anything public still needs a person (publish role)
A step that fails stops the steps that depend on it; the failure and reason stay visible in the run log.
The run is synchronous inside one Celery task (bounded: one audit, one plan, <= 7 drafts).
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tenant_now
from app.models.marketing import MarketingAudit, MarketingContent, MarketingPlan, MarketingTask
from app.models.module import Module, WorkspaceModule
from app.models.tenant import Tenant
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as content_svc

log = structlog.get_logger()

AGENCY_ACTOR = SimpleNamespace(id="agency", role="agency")   # recorded as the actor of the agency's own decisions
MAX_DRAFTS = 7
RUN_WEEKDAY, RUN_HOUR = 0, 9      # Monday 09:00 in the workspace timezone


def module_enabled(db: Session, tenant_id: str) -> bool:
    return (db.query(WorkspaceModule.id).join(Module, Module.id == WorkspaceModule.module_id)
            .filter(WorkspaceModule.workspace_id == tenant_id, WorkspaceModule.enabled.is_(True),
                    Module.code == "marketing_studio").first() is not None)


def ran_this_week(db: Session, tenant: Tenant) -> bool:
    now = get_tenant_now(tenant)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return (db.query(MarketingTask.id).filter(MarketingTask.tenant_id == tenant.id, MarketingTask.step == "run",
                                              MarketingTask.trigger == "schedule",
                                              MarketingTask.created_at >= week_start.astimezone(timezone.utc)).first()
            is not None)


def due(db: Session, tenant: Tenant) -> bool:
    now = get_tenant_now(tenant)
    return (now.weekday() == RUN_WEEKDAY and now.hour == RUN_HOUR and module_enabled(db, tenant.id)
            and not agency.get_agency(tenant)["paused"] and not ran_this_week(db, tenant))


def _task(db: Session, tenant_id: str, run_id: str, role: str, step: str, trigger: str, actor: Optional[str]) -> MarketingTask:
    t = MarketingTask(tenant_id=tenant_id, run_id=run_id, role=role, step=step, status="running", trigger=trigger,
                      created_by=actor)
    db.add(t)
    db.flush()
    return t


def _finish(t: MarketingTask, status: str, *, ref: Optional[tuple] = None, detail: Optional[dict] = None,
            error: Optional[str] = None) -> None:
    t.status, t.error = status, (error or None) and error[:2000]
    if ref:
        t.ref_type, t.ref_id = ref
    if detail is not None:
        t.detail = detail
    t.finished_at = datetime.now(timezone.utc)


def _step(db: Session, tenant: Tenant, run_id: str, role: str, step: str, trigger: str, actor: Optional[str],
          fn: Callable[[MarketingTask], Optional[bool]]) -> bool:
    """Run one step if the role allows it. Returns True if the step produced its output."""
    lvl = agency.level(tenant, role)
    allowed = lvl == "autopilot" or (trigger == "manual" and lvl == "suggest")
    t = _task(db, tenant.id, run_id, role, step, trigger, actor)
    if not allowed:
        _finish(t, "skipped", detail={"reason": f"{agency.ROLES[role][0]} is set to {lvl}"})
        db.commit()
        return False
    try:
        ok = fn(t)
    except ai.LLMTransientError as exc:
        _finish(t, "failed", error=f"The AI service is unavailable right now: {exc}")
        ok = False
    except content_svc.MarketingError as exc:
        _finish(t, "failed", error="; ".join([exc.message, *exc.problems]))
        ok = False
    except Exception as exc:  # noqa: BLE001 -- the log must show every stop, never a half-finished run
        log.exception("agency_step_crashed", tenant_id=tenant.id, step=step)
        _finish(t, "failed", error=f"Unexpected error: {type(exc).__name__}")
        ok = False
    if t.status == "running":
        _finish(t, "done" if ok else "failed")
    db.commit()
    return bool(ok)


def run_week(db: Session, tenant_id: str, *, trigger: str = "schedule", actor_id: Optional[str] = None) -> str:
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    run_id = str(uuid.uuid4())
    run = _task(db, tenant_id, run_id, "manager", "run", trigger, actor_id)
    db.commit()
    state: dict = {}

    def research(t):
        audit = MarketingAudit(tenant_id=tenant_id, measured=ai.measured_snapshot(db, tenant_id), status="pending",
                               created_by=actor_id or AGENCY_ACTOR.id)
        db.add(audit)
        db.flush()
        ai.run_audit(db, tenant_id, audit.id)
        state["audit"] = audit
        _finish(t, "done" if audit.status == "ready" else "failed", ref=("marketing_audit", audit.id), error=audit.error)
        return audit.status == "ready"

    def competitors(t):
        from app.services import marketing_research_service as research
        if not research.list_competitors(db, tenant_id):
            _finish(t, "skipped", detail={"reason": "No competitors on the list yet."})
            return False
        snaps = research.snapshot_competitors(db, tenant_id)
        brief = research.run_brief(db, tenant, actor_id or AGENCY_ACTOR.id)
        _finish(t, "done" if brief.status == "ready" else "failed", ref=("marketing_research_brief", brief.id),
                detail={"snapshots": snaps}, error=brief.error)
        return brief.status == "ready"

    def strategy(t):
        start = get_tenant_now(tenant).date() + timedelta(days=1)
        audit = state.get("audit")
        plan = MarketingPlan(tenant_id=tenant_id, period_start=start.isoformat(),
                             period_end=(start + timedelta(days=6)).isoformat(),
                             brief="Weekly agency plan for the next 7 days.",
                             audit_id=audit.id if audit is not None and audit.status == "ready" else None,
                             status="pending", created_by=actor_id or AGENCY_ACTOR.id)
        db.add(plan)
        db.flush()
        ai.run_plan(db, tenant_id, plan.id)
        state["plan"] = plan
        _finish(t, "done" if plan.status == "ready" else "failed", ref=("marketing_plan", plan.id), error=plan.error)
        return plan.status == "ready"

    def copy(t):
        plan = state.get("plan")
        if plan is None or plan.status != "ready":
            _finish(t, "skipped", detail={"reason": "No plan this week."})
            return False
        made, failed = [], []
        for entry in (plan.body or {}).get("calendar", [])[:MAX_DRAFTS]:
            item = content_svc.create_item(db, tenant_id, kind=entry["kind"], title=f"{entry['pillar']}: {entry['idea']}"[:160],
                                           actor_id=AGENCY_ACTOR.id, plan_id=plan.id, planned_for=entry["date"])
            db.flush()
            ai.run_content(db, tenant_id, item.id, None, entry["idea"])
            (made if item.current_version_id else failed).append(item.id)
            db.commit()
        state["drafts"] = made
        _finish(t, "done" if made else "failed", detail={"drafted": len(made), "failed": len(failed)},
                error=None if made else "No draft could be written.")
        return bool(made)

    def design(t):
        from app.services import marketing_image_service as images
        if not images.ai_images_enabled(tenant):
            _finish(t, "skipped", detail={"reason": "AI images are switched off."})
            return False
        queued = 0
        for item_id in state.get("drafts", []):
            item = content_svc.get_item(db, tenant_id, item_id)
            if item.kind not in ("post", "promo"):
                continue
            try:
                job = images.request_image(db, tenant, prompt=item.title.split(":", 1)[-1].strip()[:300] or item.title,
                                           model=images.image_adapter.DEFAULT_MODEL, shape="portrait",
                                           actor_id=AGENCY_ACTOR.id)
            except content_svc.MarketingError as exc:
                if exc.code == "monthly_cap_reached":
                    break
                continue
            db.commit()
            _queue_image(job.id, tenant_id)
            queued += 1
        _finish(t, "done", detail={"images_requested": queued})
        return True

    def submit(t):
        sent = 0
        for item_id in state.get("drafts", []):
            item = content_svc.get_item(db, tenant_id, item_id)
            if item.status == "draft" and item.current_version_id:
                content_svc.submit(db, tenant_id, item.id, item.current_version_id, AGENCY_ACTOR)
                sent += 1
        db.commit()
        if sent:
            agency.notify_needs_approval(db, tenant_id, "Marketing: posts ready for approval",
                                         f"The agency drafted {sent} posts for next week.")
        _finish(t, "done" if sent else "skipped", detail={"submitted": sent})
        return sent > 0

    research_ok = _step(db, tenant, run_id, "research", "audit", trigger, actor_id, research)
    _step(db, tenant, run_id, "research", "competitors", trigger, actor_id, competitors)
    plan_ok = _step(db, tenant, run_id, "strategy", "plan", trigger, actor_id, strategy)
    drafts_ok = plan_ok and _step(db, tenant, run_id, "copy", "draft", trigger, actor_id, copy)
    if drafts_ok:
        _step(db, tenant, run_id, "design", "image", trigger, actor_id, design)
        _step(db, tenant, run_id, "copy", "submit", trigger, actor_id, submit)
    summary = {"audit": research_ok, "plan": plan_ok, "drafts": len(state.get("drafts", []))}
    _finish(run, "done" if plan_ok else "failed", detail=summary,
            error=None if plan_ok else "The weekly plan could not be made; see the steps above.")
    db.commit()
    log.info("agency_run_finished", tenant_id=tenant_id, run_id=run_id, **summary)
    return run_id


def _queue_image(job_id: str, tenant_id: str) -> None:
    try:
        from app.workers.tasks.marketing_studio import generate_image
        generate_image.delay(tenant_id, job_id)
    except Exception as exc:  # noqa: BLE001 -- the image job stays pending and shows in the library panel
        log.warning("agency_image_queue_failed", tenant_id=tenant_id, job_id=job_id, error=str(exc))


def history(db: Session, tenant_id: str, limit: int = 10) -> list[dict]:
    runs = (db.query(MarketingTask).filter_by(tenant_id=tenant_id, step="run")
            .order_by(MarketingTask.created_at.desc()).limit(limit).all())
    ids = [r.run_id for r in runs]
    steps = (db.query(MarketingTask).filter(MarketingTask.tenant_id == tenant_id, MarketingTask.run_id.in_(ids),
                                            MarketingTask.step != "run")
             .order_by(MarketingTask.created_at.asc()).all()) if ids else []
    by_run: dict[str, list] = {}
    for s in steps:
        by_run.setdefault(s.run_id, []).append({"role": s.role, "step": s.step, "status": s.status, "error": s.error,
                                                "detail": s.detail, "ref_type": s.ref_type, "ref_id": s.ref_id})
    return [{"run_id": r.run_id, "status": r.status, "trigger": r.trigger, "started_at": r.created_at,
             "finished_at": r.finished_at, "summary": r.detail, "error": r.error, "steps": by_run.get(r.run_id, [])}
            for r in runs]
