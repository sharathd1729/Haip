"""The Manager: one weekly agency run per workspace (plan 18 Oct 2026, phase A; reworked in M0, 21 Oct 2026).

Steps, each logged as a marketing_tasks row under one run_id, each gated by its role's autonomy level:
  audit       (research) fresh audit: measured snapshot + AI reading
  competitors (research) competitor snapshots + research brief, when competitors are listed
  plan        (strategy) plan for the next 7 days (uses the audit and the brief)
  draft       (copy)     one draft per calendar entry (max MAX_DRAFTS), each with the plan and history as context,
                         then the brand review (M1): a blocking finding gets ONE rewrite; the AI editor adds advice
  photos      (design)   a library photo in every slot + the brand colour, saved as a new version
  image       (design)   an AI image request per post/promo, only if AI images are on and under the monthly cap
  submit      (copy)     drafts go to "waiting for approval"; a draft the review still blocks stays a draft (held)
A step that fails stops the steps that depend on it; the failure and reason stay visible in the run log.

Execution: `start_run` creates the run row; `run_step` does the NEXT unit of work (one step, or one draft) and saves
the cursor in run.detail["state"], so each unit is its own Celery task (`marketing_agency.step`): a worker restart
loses at most one unit, and the orchestrator marks a run that stopped moving as failed (STUCK_AFTER). `run_week`
runs every unit in-process (tests, scripts). The kill switch stops a run at its next unit, manual or scheduled.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.tenant_tz import get_tenant_now
from app.models.marketing import MarketingAudit, MarketingPlan, MarketingTask
from app.models.module import Module, WorkspaceModule
from app.models.tenant import Tenant
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as content_svc

log = structlog.get_logger()

AGENCY_ACTOR = SimpleNamespace(id="agency", role="agency")   # recorded as the actor of the agency's own decisions
MAX_DRAFTS = 7
RUN_WEEKDAY, RUN_HOUR = 0, 9      # Monday, from 09:00 in the workspace timezone
STUCK_AFTER = timedelta(minutes=45)
ORDER = ("audit", "competitors", "plan", "draft", "photos", "image", "submit")


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
    """Monday from 09:00 local, once a week. Any hour after 09:00 counts, so a missed tick (worker down, workspace
    paused at 09:00 and resumed later) still runs that Monday."""
    now = get_tenant_now(tenant)
    return (now.weekday() == RUN_WEEKDAY and now.hour >= RUN_HOUR and module_enabled(db, tenant.id)
            and not agency.get_agency(tenant)["paused"] and not ran_this_week(db, tenant))


def running(db: Session, tenant_id: str) -> Optional[MarketingTask]:
    return (db.query(MarketingTask)
            .filter(MarketingTask.tenant_id == tenant_id, MarketingTask.step == "run", MarketingTask.status == "running",
                    MarketingTask.updated_at >= datetime.now(timezone.utc) - STUCK_AFTER).first())


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


def _allowed(tenant: Tenant, role: str, trigger: str) -> tuple[bool, str]:
    lvl = agency.level(tenant, role)
    return lvl == "autopilot" or (trigger == "manual" and lvl == "suggest"), lvl


def _guard(t: MarketingTask, tenant_id: str, step: str, fn: Callable[[], Optional[bool]]) -> bool:
    try:
        ok = fn()
    except ai.LLMTransientError as exc:
        _finish(t, "failed", error=f"The AI service is unavailable right now: {exc}")
        ok = False
    except content_svc.MarketingError as exc:
        _finish(t, "failed", error="; ".join([exc.message, *exc.problems]))
        ok = False
    except Exception as exc:  # noqa: BLE001 -- the log must show every stop, never a half-finished run
        log.exception("agency_step_crashed", tenant_id=tenant_id, step=step)
        _finish(t, "failed", error=f"Unexpected error: {type(exc).__name__}")
        ok = False
    if t.status == "running":
        _finish(t, "done" if ok else "failed")
    return bool(ok)


def _step(db: Session, tenant: Tenant, run: MarketingTask, role: str, step: str, fn: Callable[[MarketingTask], Optional[bool]]) -> bool:
    """Run one whole step if the role allows it. Returns True if the step produced its output."""
    allowed, lvl = _allowed(tenant, role, run.trigger)
    t = _task(db, tenant.id, run.run_id, role, step, run.trigger, run.created_by)
    if not allowed:
        _finish(t, "skipped", detail={"reason": f"{agency.ROLES[role][0]} is set to {lvl}"})
        db.commit()
        return False
    ok = _guard(t, tenant.id, step, lambda: fn(t))
    db.commit()
    return ok


# ── Steps ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _audit(db, tenant, run, st):
    def fn(t):
        audit = MarketingAudit(tenant_id=tenant.id, measured=ai.measured_snapshot(db, tenant.id), status="pending",
                               created_by=run.created_by or AGENCY_ACTOR.id)
        db.add(audit)
        db.flush()
        ai.run_audit(db, tenant.id, audit.id)
        st["audit_id"] = audit.id if audit.status == "ready" else None
        _finish(t, "done" if audit.status == "ready" else "failed", ref=("marketing_audit", audit.id), error=audit.error)
        return audit.status == "ready"
    st["audit_ok"] = _step(db, tenant, run, "research", "audit", fn)
    return "competitors"


def _competitors(db, tenant, run, st):
    def fn(t):
        from app.services import marketing_research_service as research
        if not research.list_competitors(db, tenant.id):
            _finish(t, "skipped", detail={"reason": "No competitors on the list yet."})
            return False
        snaps = research.snapshot_competitors(db, tenant.id)
        brief = research.run_brief(db, tenant, run.created_by or AGENCY_ACTOR.id)
        _finish(t, "done" if brief.status == "ready" else "failed", ref=("marketing_research_brief", brief.id),
                detail={"snapshots": snaps}, error=brief.error)
        return brief.status == "ready"
    _step(db, tenant, run, "research", "competitors", fn)
    return "plan"


def _plan(db, tenant, run, st):
    def fn(t):
        start = get_tenant_now(tenant).date() + timedelta(days=1)
        plan = MarketingPlan(tenant_id=tenant.id, period_start=start.isoformat(),
                             period_end=(start + timedelta(days=6)).isoformat(),
                             brief="Weekly agency plan for the next 7 days.", audit_id=st.get("audit_id"),
                             status="pending", created_by=run.created_by or AGENCY_ACTOR.id)
        db.add(plan)
        db.flush()
        ai.run_plan(db, tenant.id, plan.id)
        st["plan_id"] = plan.id if plan.status == "ready" else None
        _finish(t, "done" if plan.status == "ready" else "failed", ref=("marketing_plan", plan.id), error=plan.error)
        return plan.status == "ready"
    st["plan_ok"] = _step(db, tenant, run, "strategy", "plan", fn)
    return "draft" if st["plan_ok"] else None


def _draft(db, tenant, run, st):
    """One calendar entry per call; the step's task row collects the counts."""
    plan = db.query(MarketingPlan).filter_by(id=st.get("plan_id"), tenant_id=tenant.id).first()
    entries = ((plan.body or {}).get("calendar", []) if plan is not None else [])[:MAX_DRAFTS]
    if not st.get("draft_task"):
        allowed, lvl = _allowed(tenant, "copy", run.trigger)
        t = _task(db, tenant.id, run.run_id, "copy", "draft", run.trigger, run.created_by)
        if not allowed or not entries:
            _finish(t, "skipped", detail={"reason": f"{agency.ROLES['copy'][0]} is set to {lvl}" if not allowed
                                          else "The plan has no calendar entries."})
            return None
        st.update(draft_task=t.id, cursor=0, drafts=[], failed=0, rewritten=0)
    t = db.query(MarketingTask).filter_by(id=st["draft_task"], tenant_id=tenant.id).one()
    i = st["cursor"]
    if i < len(entries):
        entry = entries[i]
        item = content_svc.create_item(db, tenant.id, kind=entry["kind"], title=f"{entry['pillar']}: {entry['idea']}"[:160],
                                       actor_id=AGENCY_ACTOR.id, plan_id=plan.id, planned_for=entry["date"])
        db.flush()
        try:
            ai.run_content(db, tenant.id, item.id, None, entry["idea"])
        except ai.LLMTransientError as exc:
            item.generation_status, item.generation_error = "failed", f"The AI service is unavailable: {exc}"[:2000]
        if item.current_version_id:
            st["drafts"] = [*st["drafts"], item.id]
            st["rewritten"] = st.get("rewritten", 0) + _review_draft(db, tenant, item, entry["idea"])
        else:
            st["failed"] += 1
        st["cursor"] = i + 1
        t.detail = {"drafted": len(st["drafts"]), "failed": st["failed"], "rewritten": st.get("rewritten", 0),
                    "of": len(entries)}
        flag_modified(t, "detail")
        if st["cursor"] < len(entries):
            return "draft"
    made = bool(st["drafts"])
    _finish(t, "done" if made else "failed", detail={"drafted": len(st["drafts"]), "failed": st["failed"],
                                                     "rewritten": st.get("rewritten", 0)},
            error=None if made else "No draft could be written.")
    return "photos" if made else None


def _review_draft(db, tenant, item, idea: str) -> int:
    """Brand review of a fresh draft. A blocking finding gets one rewrite with the findings as the brief; then the AI
    editor adds advice. Returns 1 if the draft was rewritten. Provider trouble never loses the draft."""
    from app.services import marketing_review_service as review
    rewritten = 0
    rev = review.current(db, tenant, item)
    if rev is not None and rev.blocking:
        try:
            ai.run_content(db, tenant.id, item.id, None, review.fix_brief(idea, rev.findings))
            rewritten = 1
        except ai.LLMTransientError as exc:
            log.info("agency_rewrite_skipped", tenant_id=tenant.id, item_id=item.id, error=str(exc)[:200])
    try:
        review.run_ai(db, tenant, item.id)
    except ai.LLMTransientError as exc:
        row = review.current(db, tenant, item)
        if row is not None:
            row.ai_status, row.ai_error = "failed", f"The AI editor is unavailable right now: {exc}"[:2000]
    return rewritten


def _photos(db, tenant, run, st):
    def fn(t):
        from app.services import marketing_photos as photos
        lib = photos.library(db, tenant.id)
        if not lib:
            _finish(t, "skipped", detail={"reason": "The photo library is empty; add photos so posts can be filled."})
            return False
        used = photos.recent_use(db, tenant.id)
        filled = sum(photos.attach_photos(db, tenant, item_id, photos=lib, used=used) for item_id in st.get("drafts", []))
        _finish(t, "done", detail={"slots_filled": filled})
        return True
    _step(db, tenant, run, "design", "photos", fn)
    return "image"


def _image(db, tenant, run, st):
    def fn(t):
        from app.services import marketing_image_service as images
        if not images.ai_images_enabled(tenant):
            _finish(t, "skipped", detail={"reason": "AI images are switched off."})
            return False
        queued = 0
        for item_id in st.get("drafts", []):
            item = content_svc.get_item(db, tenant.id, item_id)
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
            _queue_image(job.id, tenant.id)
            queued += 1
        _finish(t, "done", detail={"images_requested": queued})
        return True
    _step(db, tenant, run, "design", "image", fn)
    return "submit"


def _submit(db, tenant, run, st):
    def fn(t):
        from app.services import marketing_review_service as review
        sent, held = 0, 0
        for item_id in st.get("drafts", []):
            item = content_svc.get_item(db, tenant.id, item_id)
            if item.status == "draft" and item.current_version_id:
                rev = review.current(db, tenant, item)
                if rev is not None and rev.blocking:
                    held += 1                          # stays a draft; its findings show in the Content tab
                    continue
                content_svc.submit(db, tenant.id, item.id, item.current_version_id, AGENCY_ACTOR)
                sent += 1
        db.commit()
        if sent:
            agency.notify_needs_approval(db, tenant.id, "Marketing: posts ready for approval",
                                         f"The agency drafted {sent} posts for next week.")
        _finish(t, "done" if sent else "skipped", detail={"submitted": sent, "held": held,
                                                          **({"reason": f"{held} held back by the brand review"}
                                                             if held and not sent else {})})
        return sent > 0
    _step(db, tenant, run, "copy", "submit", fn)
    return None


STEPS: dict[str, Callable] = {"audit": _audit, "competitors": _competitors, "plan": _plan, "draft": _draft,
                              "photos": _photos, "image": _image, "submit": _submit}


# ── Driver ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def start_run(db: Session, tenant_id: str, *, trigger: str = "schedule", actor_id: Optional[str] = None) -> MarketingTask:
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    run = _task(db, tenant_id, str(uuid.uuid4()), "manager", "run", trigger, actor_id)
    if agency.get_agency(tenant)["paused"]:
        _finish(run, "skipped", detail={"reason": "The agency is paused."})
    else:
        run.detail = {"state": {"next": ORDER[0]}}
    db.commit()
    return run


def _fail_open_steps(db: Session, run: MarketingTask, reason: str) -> None:
    (db.query(MarketingTask).filter(MarketingTask.tenant_id == run.tenant_id, MarketingTask.run_id == run.run_id,
                                    MarketingTask.step != "run", MarketingTask.status == "running")
     .update({"status": "failed", "error": reason, "finished_at": datetime.now(timezone.utc)}, synchronize_session=False))


def _close(run: MarketingTask, st: dict, *, stopped: Optional[str] = None) -> None:
    plan_ok = bool(st.get("plan_ok"))
    summary = {"audit": bool(st.get("audit_ok")), "plan": plan_ok, "drafts": len(st.get("drafts", [])), "state": st}
    if stopped:
        _finish(run, "failed", detail=summary, error=stopped)
    else:
        _finish(run, "done" if plan_ok else "failed", detail=summary,
                error=None if plan_ok else "The weekly plan could not be made; see the steps above.")


def run_step(db: Session, tenant_id: str, run_id: str) -> bool:
    """Do the next unit of a run. Returns True while there is more to do."""
    run = db.query(MarketingTask).filter_by(tenant_id=tenant_id, run_id=run_id, step="run").first()
    if run is None or run.status != "running":
        return False
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    st = dict((run.detail or {}).get("state") or {})
    nxt = st.get("next")
    if agency.get_agency(tenant)["paused"]:
        _fail_open_steps(db, run, "Stopped: the agency was paused.")
        _close(run, st, stopped="Stopped: the agency was paused.")
        db.commit()
        return False
    try:
        nxt = STEPS[nxt](db, tenant, run, st) if nxt in STEPS else None
    except Exception as exc:  # noqa: BLE001 -- e.g. the database went away mid-step: record it, never hang
        db.rollback()
        log.exception("agency_run_step_crashed", tenant_id=tenant_id, run_id=run_id, step=st.get("next"))
        run = db.query(MarketingTask).filter_by(tenant_id=tenant_id, run_id=run_id, step="run").one()
        _fail_open_steps(db, run, f"Unexpected error: {type(exc).__name__}")
        _close(run, st, stopped=f"Stopped at {st.get('next')}: unexpected error ({type(exc).__name__}).")
        db.commit()
        return False
    st["next"] = nxt
    if nxt is None:
        _close(run, st)
        log.info("agency_run_finished", tenant_id=tenant_id, run_id=run_id, drafts=len(st.get("drafts", [])))
    else:
        run.detail = {**(run.detail or {}), "state": st}
        run.updated_at = datetime.now(timezone.utc)      # progress marker for the stuck-run sweep
        flag_modified(run, "detail")
    db.commit()
    return nxt is not None


def run_week(db: Session, tenant_id: str, *, trigger: str = "schedule", actor_id: Optional[str] = None) -> str:
    """Every unit in-process. The Celery path is start_run + one `marketing_agency.step` task per unit."""
    run = start_run(db, tenant_id, trigger=trigger, actor_id=actor_id)
    while run_step(db, tenant_id, run.run_id):
        pass
    return run.run_id


def sweep_stuck(db: Session, now: Optional[datetime] = None) -> int:
    """Runs that have not moved for STUCK_AFTER (worker restarted, task lost) are closed as failed, with their open steps."""
    cutoff = (now or datetime.now(timezone.utc)) - STUCK_AFTER
    stuck = (db.query(MarketingTask).filter(MarketingTask.step == "run", MarketingTask.status == "running",
                                            MarketingTask.updated_at < cutoff).limit(100).all())
    for run in stuck:
        st = dict((run.detail or {}).get("state") or {})
        _fail_open_steps(db, run, "Stopped: the worker did not finish this step.")
        _close(run, st, stopped=f"Stopped at {st.get('next')}: no progress for {int(STUCK_AFTER.total_seconds() // 60)} minutes.")
        db.commit()
    return len(stuck)


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

    def summary(r):
        return {k: v for k, v in (r.detail or {}).items() if k != "state"} or None
    return [{"run_id": r.run_id, "status": r.status, "trigger": r.trigger, "started_at": r.created_at,
             "finished_at": r.finished_at, "summary": summary(r), "error": r.error,
             "next_step": ((r.detail or {}).get("state") or {}).get("next") if r.status == "running" else None,
             "steps": by_run.get(r.run_id, [])} for r in runs]
