"""Approve / reject a proposal and run its steps (E2).

approve(): only an OWNER (checked by the endpoint / the WhatsApp tap), only while it awaits a decision (guarded UPDATE: a
second tap is a 409), only for the plan the owner saw (``plan_sha``), and an R3 plan (guests, public, money) only in the
app. The finding must still be open. Audited ``chief.proposal_approved|rejected``.

run(): claims the proposal (guarded approved|waiting -> executing), then runs steps from ``step_index``: each in a
savepoint, its result stored before moving on. A waiting step parks the proposal (``waiting`` + next_check_at; beat
chief.advance_all_tenants re-checks it); a failed one stops it and tells the owners. Guards at run time: the Executive on
and not paused (kill switch), the daily action cap. Every step audited ``chief.step_done|step_failed``.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.chief import ChiefProposal
from app.models.insight import Insight
from app.services.chief import settings as chief_settings
from app.services.chief import steps as step_lib

log = structlog.get_logger()

OUTCOME_AFTER = timedelta(days=14)


class DecisionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(db: Session, p: ChiefProposal, action: str, actor_id: str | None, **payload) -> None:
    append_audit(
        db,
        tenant_id=p.tenant_id,
        actor_user_id=actor_id,
        action=action,
        target_type="chief_proposal",
        target_id=p.id,
        payload={"code": p.code, **({} if actor_id else {"actor": "chief"}), **payload},
    )


def _claim(db: Session, p: ChiefProposal, frm: tuple, to: str) -> bool:
    n = (
        db.query(ChiefProposal)
        .filter(ChiefProposal.id == p.id, ChiefProposal.status.in_(frm))
        .update({ChiefProposal.status: to}, synchronize_session=False)
    )
    db.refresh(p)
    return n == 1


def approve(db: Session, tenant, p: ChiefProposal, user_id: str, plan_sha: str, via: str = "app") -> ChiefProposal:
    cfg = chief_settings.get(tenant)
    if not cfg.enabled:
        raise DecisionError(409, "The AI Executive is switched off.")
    if p.status != "awaiting_approval":
        raise DecisionError(409, "This proposal was already decided.")
    if plan_sha != p.plan_sha:
        raise DecisionError(409, "The plan changed since you opened it. Open it again.")
    if via == "whatsapp" and p.risk_tier == "R3":
        raise DecisionError(
            403, "This change reaches guests or money: approve it in the app, where you see the exact text."
        )
    finding = db.query(Insight).filter_by(id=p.finding_id, tenant_id=p.tenant_id).first()
    if finding is None or finding.is_auto_resolved or finding.is_dismissed:
        p.status, p.finished_at = "expired", _now()
        _audit(db, p, "chief.proposal_expired", None)
        raise DecisionError(409, "The problem went away, so this proposal is no longer needed.")
    if not _claim(db, p, ("awaiting_approval",), "approved"):
        raise DecisionError(409, "This proposal was already decided.")
    p.decided_by, p.decided_at, p.decided_via = user_id, _now(), via
    p.baseline = {"numbers": finding.numbers or {}, "at": _now().isoformat()}
    _audit(db, p, "chief.proposal_approved", user_id, via=via, tier=p.risk_tier, plan_sha=p.plan_sha)
    return p


def reject(
    db: Session, tenant, p: ChiefProposal, user_id: str, reason: str | None, note: str | None = None, via: str = "app"
) -> ChiefProposal:
    if not _claim(db, p, ("awaiting_approval",), "rejected"):
        raise DecisionError(409, "This proposal was already decided.")
    p.decided_by, p.decided_at, p.decided_via = user_id, _now(), via
    p.decision_reason, p.decision_note, p.finished_at = reason, note, _now()
    _audit(db, p, "chief.proposal_rejected", user_id, via=via, reason=reason)
    return p


def _day_start(now: datetime) -> datetime:
    """Midnight IST (the cap is per business day; every workspace runs on IST today)."""
    from app.services.date_presets import IST

    return datetime.combine(now.astimezone(IST).date(), time.min, tzinfo=IST).astimezone(UTC)


def actions_today(db: Session, tenant_id: str, since: datetime) -> int:
    n = 0
    for (steps,) in db.query(ChiefProposal.steps).filter(
        ChiefProposal.tenant_id == tenant_id, ChiefProposal.updated_at >= since
    ):
        for s in steps or []:
            at = s.get("at")
            if (
                s.get("status") == "done"
                and s["type"] not in step_lib.NOT_ACTIONS
                and at
                and datetime.fromisoformat(at) >= since
            ):
                n += 1
    return n


def _notify_owners(db: Session, tenant_id: str, title: str, body: str) -> None:
    from app.models.user import User, UserRole
    from app.services.push_service import send_to_tenant

    for u in db.query(User).filter(User.tenant_id == tenant_id, User.role == UserRole.OWNER, User.is_active.is_(True)):
        send_to_tenant(db, tenant_id, title, body, url="/dashboard/analyst", tag="chief", user_id=u.id)


def run(db: Session, tenant, p: ChiefProposal, now: datetime | None = None) -> str:
    """Run what can run now. Returns done | waiting | failed | paused | capped | busy. Commits after every step."""
    now = now or _now()
    cfg = chief_settings.get(tenant)
    if not cfg.enabled or cfg.paused:
        return "paused"
    if not _claim(db, p, ("approved", "waiting"), "executing"):
        return "busy"
    db.commit()  # the claim is visible to any other worker before a step starts
    actor = p.decided_by
    since = _day_start(now)
    steps = [dict(s) for s in p.steps]
    while p.step_index < len(steps):
        s = steps[p.step_index]
        if s["type"] not in step_lib.NOT_ACTIONS and actions_today(db, p.tenant_id, since) >= cfg.daily_action_cap:
            p.status, p.next_check_at = "approved", since + timedelta(days=1, minutes=5)
            db.commit()
            log.info("chief_daily_cap_reached", tenant_id=p.tenant_id, proposal_id=p.id)
            return "capped"
        s.setdefault("started_at", now.isoformat())
        try:
            # No savepoint: some services commit on their own (wa_lead_pack.create_drafts). Every step is safe to repeat.
            status, result, reason, retry_at = step_lib.RUNNERS[s["type"]](db, tenant, p, s, actor, now)
        except Exception as exc:  # noqa: BLE001 -- recorded on the step; the proposal stops, the step's own writes are undone
            db.rollback()
            db.refresh(p)
            log.exception("chief_step_crashed", tenant_id=p.tenant_id, proposal_id=p.id, step=s["type"])
            status, result, reason, retry_at = "failed", None, f"{type(exc).__name__}: {exc}"[:500], None
        s.update(status=status, result=result, reason=reason, at=now.isoformat())
        p.steps = [dict(x) for x in steps]
        if status == "waiting":
            p.status, p.next_check_at = "waiting", retry_at or now + step_lib.WAIT_RECHECK
            db.commit()
            return "waiting"
        if status == "failed":
            p.status, p.failure, p.finished_at = "failed", reason, now
            _audit(db, p, "chief.step_failed", actor, step=s["type"], reason=reason)
            db.commit()
            _notify_owners(db, p.tenant_id, "AI Executive: a step failed", f"{p.title}: {reason}")
            return "failed"
        _audit(db, p, "chief.step_done", actor, step=s["type"], result=result)
        p.step_index += 1
        db.commit()
    p.status, p.finished_at, p.check_due_at, p.next_check_at = "done", now, now + OUTCOME_AFTER, None
    _audit(db, p, "chief.proposal_done", actor)
    db.commit()
    _notify_owners(db, p.tenant_id, "AI Executive: done", p.title)
    return "done"


def due(db: Session, tenant_id: str, now: datetime | None = None) -> list[ChiefProposal]:
    """Approved proposals not yet started (or held by the cap) and waiting ones whose re-check time has come."""
    now = now or _now()
    return [
        p
        for p in db.query(ChiefProposal)
        .filter(ChiefProposal.tenant_id == tenant_id, ChiefProposal.status.in_(("approved", "waiting")))
        .all()
        if p.next_check_at is None or _aware(p.next_check_at) <= now
    ]


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
