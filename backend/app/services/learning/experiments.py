"""The experiment lifecycle (agent_experiments). Every transition is a chained audit row ``learning.experiment_<status>``.

  propose   validate the diff (catalogue) -> "proposed" -> advance()
  advance   the area's autonomy level (learning.settings): watch = stays proposed (report only); suggest, or experiments not
            allowed = "awaiting_approval" (one tap by an owner / manager; area "prices" = owner only); act = start()
  start     the control must be free (one running test per control, none on the same metric) -> bench gate (bench_gate.check):
            a failed guarantee = "bench_failed", never runs; else "running" (assignment: new conversations, 50/50, sticky)
  evaluate  daily (Celery learning.evaluate_all): evaluate.decide -> keep (the diff becomes the base setting, before/after kept for
            Undo, a lesson is written) | rolled_back | stopped ("no clear difference", base kept) | continue
  undo      a kept change restores the setting it replaced, if nobody changed it since (409 otherwise)
  pause_all the kill switch: every running experiment is stopped at once; every conversation reads the base settings
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.analyst import AgentExperiment
from app.services.learning import bench_gate, catalogue
from app.services.learning import evaluate as ev
from app.services.learning import settings as ls

log = structlog.get_logger()


class ExperimentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(db: Session, exp: AgentExperiment, actor_id: Optional[str], extra: Optional[dict] = None) -> None:
    payload = {"change_type": exp.change_type, "area": exp.area, "diff": exp.diff, **(extra or {})}
    if actor_id is None:
        payload["actor"] = "learning"
    append_audit(db, tenant_id=exp.tenant_id, actor_user_id=actor_id, action=f"learning.experiment_{exp.status}",
                 target_type="agent_experiment", target_id=exp.id, payload=payload)


def _set(db: Session, exp: AgentExperiment, status: str, actor_id: Optional[str], *, reason: str = "", by: str = "system",
         extra: Optional[dict] = None) -> None:
    exp.status = status
    exp.decision = {**(exp.decision or {}), "result": status, "reason": reason, "at": _now().isoformat()}
    exp.decided_by = by
    exp.decided_by_user_id = actor_id
    db.flush()
    _audit(db, exp, actor_id, {"reason": reason, **(extra or {})})


def get(db: Session, tenant_id: str, exp_id: str) -> AgentExperiment:
    exp = db.query(AgentExperiment).filter_by(tenant_id=tenant_id, id=exp_id).first()
    if exp is None:
        raise ExperimentError(404, "not_found", "Experiment not found.")
    return exp


def propose(db: Session, tenant, change_type: str, diff: dict, *, rationale: Optional[dict] = None, title: Optional[str] = None,
            target_metric: Optional[str] = None, source_report_id: Optional[str] = None, proposed_by: Optional[str] = None,
            bench_runner=None, defer: bool = False) -> AgentExperiment:
    """``defer`` (request handlers): an "act" proposal is marked starting and the caller queues learning.start_experiment, so
    the bench gate never runs inside a request."""
    try:
        clean = catalogue.validate(db, tenant, change_type, diff)
    except catalogue.ChangeRefused as exc:
        raise ExperimentError(422, exc.code, exc.message)
    t = catalogue.TYPES[change_type]
    metric = target_metric if target_metric in catalogue.METRICS else t.metric
    d = ls.get(tenant).experiments
    exp = AgentExperiment(tenant_id=tenant.id, change_type=change_type, area=t.area, control=t.control,
                          title=(title or catalogue.describe(change_type, clean))[:300], rationale=rationale or {}, diff=clean,
                          target_metric=metric, min_sample_per_arm=d.min_sample_per_arm, max_days=d.max_days,
                          stop_loss={"relative": d.stop_loss_relative, "p": d.stop_loss_p, "keep_p": d.keep_p},
                          status="proposed", assignment_rule={"unit": "conversation", "split": 0.5, "salt": "experiment_id"},
                          source_report_id=source_report_id, proposed_by=proposed_by)
    db.add(exp)
    db.flush()
    _audit(db, exp, proposed_by, {"title": exp.title})
    advance(db, tenant, exp, bench_runner=bench_runner, defer=defer)
    return exp


STARTING = "starting: the bench is running"


def advance(db: Session, tenant, exp: AgentExperiment, *, bench_runner=None, defer: bool = False) -> AgentExperiment:
    s = ls.get(tenant)
    lvl = ls.level(tenant, exp.area)
    if s.paused:
        exp.decision = {"result": "proposed", "reason": "learning is paused"}
        return exp
    if lvl == "watch":
        exp.decision = {"result": "proposed", "reason": "area set to watch: report only"}
        return exp
    if lvl == "suggest" or not s.experiments_allowed:
        _set(db, exp, "awaiting_approval", None,
             reason="needs a person's approval" if lvl == "suggest" else "experiments are not allowed to start by themselves")
        return exp
    if defer:
        exp.decision = {"result": "proposed", "reason": STARTING}
        return exp
    return start(db, tenant, exp, actor_id=None, bench_runner=bench_runner)


def _approver_ok(exp: AgentExperiment, user) -> bool:
    role = getattr(user.role, "value", user.role)
    return role == "owner" if exp.area == "prices" else role in ("owner", "manager")


def approve(db: Session, tenant, exp_id: str, user, *, bench_runner=None, defer: bool = False) -> AgentExperiment:
    exp = get(db, tenant.id, exp_id)
    if not _approver_ok(exp, user):
        raise ExperimentError(403, "owner_only", "Only the owner approves changes about prices.")
    if exp.status not in ("awaiting_approval", "proposed"):
        raise ExperimentError(409, "not_waiting", f"This change is {exp.status.replace('_', ' ')}.")
    if ls.get(tenant).paused:
        raise ExperimentError(409, "paused", "Learning is paused. Turn it back on first.")
    exp.approved_by, exp.approved_at = user.id, _now()
    append_audit(db, tenant_id=tenant.id, actor_user_id=user.id, action="learning.experiment_approved",
                 target_type="agent_experiment", target_id=exp.id, payload={"change_type": exp.change_type})
    if defer:
        exp.decision = {"result": exp.status, "reason": STARTING}
        return exp
    return start(db, tenant, exp, actor_id=user.id, bench_runner=bench_runner)


def reject(db: Session, tenant, exp_id: str, user) -> AgentExperiment:
    exp = get(db, tenant.id, exp_id)
    if exp.status not in ("awaiting_approval", "proposed", "bench_failed"):
        raise ExperimentError(409, "not_waiting", f"This change is {exp.status.replace('_', ' ')}.")
    _set(db, exp, "rejected", user.id, reason="not now", by="user")
    return exp


def start(db: Session, tenant, exp: AgentExperiment, *, actor_id: Optional[str], bench_runner=None) -> AgentExperiment:
    busy = db.query(AgentExperiment).filter(AgentExperiment.tenant_id == tenant.id, AgentExperiment.status == "running",
                                            AgentExperiment.id != exp.id,
                                            (AgentExperiment.control == exp.control) | (AgentExperiment.target_metric == exp.target_metric)
                                            ).first()
    if busy is not None:
        exp.decision = {"result": exp.status, "reason": f"waiting: '{busy.title}' is already testing this"}
        if exp.status == "proposed" and actor_id:
            exp.status = "awaiting_approval"
        return exp
    result = bench_gate.check(db, tenant, exp, runner=bench_runner)
    exp.bench = result
    by = "user" if actor_id else "system"
    if not result["passed"]:
        _set(db, exp, "bench_failed", actor_id, reason=f"{len(result['failed'])} bench scenario(s) failed", by=by)
        return exp
    exp.started_at = _now()
    try:
        with db.begin_nested():
            _set(db, exp, "running", actor_id, reason="bench passed", by=by)
    except IntegrityError:                           # another test grabbed the control at the same moment
        db.refresh(exp)
        exp.started_at = None
        exp.decision = {"result": exp.status, "reason": "waiting: another test started on this control"}
    return exp


def _keep(db: Session, tenant, exp: AgentExperiment, verdict: dict) -> None:
    before = catalogue.snapshot(tenant, exp.change_type)
    after = catalogue.after_value(db, tenant, exp.change_type, exp.diff or {})
    catalogue.write(db, tenant, exp.change_type, after, None, actor="learning")
    exp.applied_before, exp.applied_after = before, after
    exp.ended_at = _now()
    _set(db, exp, "kept", None, reason=verdict["reason"], extra={"test": verdict.get("test")})
    try:
        from app.services.learning import lessons
        lessons.from_experiment(db, exp)
    except Exception as exc:  # noqa: BLE001 -- a lesson is a bonus; the keep stands
        log.warning("learning_lesson_failed", experiment_id=exp.id, error=type(exc).__name__)


def evaluate_one(db: Session, tenant, exp: AgentExperiment, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    out = ev.evaluate(db, exp, now, ls.get(tenant).experiments)
    exp.metrics = {**out["counts"], "test": out["verdict"]["test"], "target": exp.target_metric,
                   "evaluated_at": now.isoformat(), "elapsed_days": out["elapsed_days"]}
    v = out["verdict"]
    if v["result"] == "keep":
        _keep(db, tenant, exp, v)
    elif v["result"] in ("rollback", "stop"):
        exp.ended_at = now
        _set(db, exp, "rolled_back" if v["result"] == "rollback" else "stopped", None, reason=v["reason"],
             extra={"test": v.get("test")})
        if v["result"] == "rollback":
            try:
                from app.services.learning import lessons
                lessons.contradicted_by(db, exp)
            except Exception as exc:  # noqa: BLE001
                log.warning("learning_lesson_retire_failed", experiment_id=exp.id, error=type(exc).__name__)
    db.flush()
    return {"experiment_id": exp.id, **v}


def evaluate_tenant(db: Session, tenant, now: Optional[datetime] = None) -> list[dict]:
    if ls.get(tenant).paused:
        return []
    return [evaluate_one(db, tenant, e, now) for e in db.query(AgentExperiment).filter_by(tenant_id=tenant.id, status="running").all()]


def undo(db: Session, tenant, exp_id: str, user) -> AgentExperiment:
    exp = get(db, tenant.id, exp_id)
    if exp.status != "kept" or exp.undone_at is not None:
        raise ExperimentError(409, "not_kept", "Only a kept change can be undone, once.")
    if exp.area == "prices" and getattr(user.role, "value", user.role) != "owner":
        raise ExperimentError(403, "owner_only", "Only the owner undoes changes about prices.")
    if catalogue.snapshot(tenant, exp.change_type) != exp.applied_after:
        raise ExperimentError(409, "changed_since", "This setting was changed after the test; change it in Settings instead.")
    catalogue.write(db, tenant, exp.change_type, exp.applied_before, user.id, actor="learning_undo")
    exp.undone_at, exp.undone_by = _now(), user.id
    append_audit(db, tenant_id=tenant.id, actor_user_id=user.id, action="learning.change_undone", target_type="agent_experiment",
                 target_id=exp.id, payload={"change_type": exp.change_type, "restored": exp.applied_before})
    try:
        from app.services.learning import lessons
        lessons.retire_for(db, exp, "the owner undid the change")
    except Exception:  # noqa: BLE001
        pass
    return exp


def pause_all(db: Session, tenant, actor_id: Optional[str]) -> int:
    rows = db.query(AgentExperiment).filter_by(tenant_id=tenant.id, status="running").all()
    for exp in rows:
        exp.ended_at = _now()
        _set(db, exp, "stopped", actor_id, reason="learning paused (kill switch)", by="user" if actor_id else "system")
    return len(rows)


def view(exp: AgentExperiment, now: Optional[datetime] = None) -> dict:
    m = exp.metrics or {}
    target = exp.target_metric

    def arm(a):
        block = m.get(a) or {}
        return {"assigned": block.get("assigned", 0), **(block.get(target) or {"n": 0, "x": 0, "rate": None})}
    return {"id": exp.id, "change_type": exp.change_type, "area": exp.area, "control": exp.control, "title": exp.title,
            "status": exp.status, "diff": exp.diff, "target_metric": target, "rationale": exp.rationale,
            "control_arm": arm("control"), "treatment_arm": arm("treatment"), "test": m.get("test"),
            "days_left": ev.days_left(exp, now or _now()) if exp.status == "running" else None,
            "decision": exp.decision, "decided_by": exp.decided_by, "bench": {k: v for k, v in (exp.bench or {}).items() if k != "scenarios"},
            "undo_available": exp.status == "kept" and exp.undone_at is None, "undone_at": exp.undone_at.isoformat() if exp.undone_at else None,
            "started_at": exp.started_at.isoformat() if exp.started_at else None,
            "ended_at": exp.ended_at.isoformat() if exp.ended_at else None,
            "created_at": exp.created_at.isoformat() if exp.created_at else None, "source_report_id": exp.source_report_id}


def board(db: Session, tenant_id: str) -> dict:
    """The owner's three lists: changes made within limits, changes suggested, tests running."""
    rows = db.query(AgentExperiment).filter_by(tenant_id=tenant_id).order_by(AgentExperiment.created_at.desc()).limit(100).all()
    now = _now()
    return {"made": [view(e, now) for e in rows if e.status in ("kept", "rolled_back", "stopped", "bench_failed")][:20],
            "suggested": [view(e, now) for e in rows if e.status in ("awaiting_approval", "proposed")][:20],
            "running": [view(e, now) for e in rows if e.status == "running"]}
