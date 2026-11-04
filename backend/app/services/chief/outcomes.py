"""Did the fix work? (E4) For each DONE proposal past its ``check_due_at`` (14 days after it finished): the finding resolved
by itself = improved; otherwise its primary number now vs the baseline kept at approval (tuning.verdict, 20% either way).
The verdict is stored on the proposal (``outcome``), audited ``chief.outcome_recorded`` and fed to tuning.on_outcome.
Then any detector that became eligible for autopilot is OFFERED to the owners once (a push); nothing switches on by itself.

Called daily by Celery ``chief.outcomes_all_tenants`` (06:50 IST, before the daily detection pass).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.chief import ChiefProposal
from app.models.insight import Insight
from app.services.chief import catalogue, tuning

log = structlog.get_logger()


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def check_tenant(db: Session, tenant, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rows = (
        db.query(ChiefProposal)
        .filter(
            ChiefProposal.tenant_id == tenant.id, ChiefProposal.status == "done", ChiefProposal.check_due_at.isnot(None)
        )
        .all()
    )
    checked = 0
    for p in rows:
        if p.outcome or _aware(p.check_due_at) > now:  # JSON null vs SQL NULL differs by database: check here
            continue
        f = db.query(Insight).filter_by(id=p.finding_id, tenant_id=tenant.id).first()
        before = ((p.baseline or {}).get("numbers")) or {}
        after = (f.numbers if f is not None else None) or {}
        resolved = f is None or bool(f.is_auto_resolved)
        v = tuning.verdict(p.code, before, after, resolved)
        p.outcome = {"verdict": v, "before": before, "after": after, "resolved": resolved, "at": now.isoformat()}
        append_audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=None,
            action="chief.outcome_recorded",
            target_type="chief_proposal",
            target_id=p.id,
            payload={"actor": "chief", "code": p.code, "verdict": v},
        )
        tuning.on_outcome(db, tenant.id, p.code, v)
        checked += 1
    offered = offer_autopilot(db, tenant, now)
    return {"checked": checked, "offered": offered}


def offer_autopilot(db: Session, tenant, now: datetime) -> list[str]:
    from app.models.user import User, UserRole
    from app.services.push_service import send_to_tenant

    out = []
    for det in catalogue.CATALOGUE:
        t = tuning.get(db, tenant.id, det.code)
        if t is None or t.autopilot_by or t.autopilot_offered_at or not tuning.eligible(db, tenant.id, det.code, now):
            continue
        t.autopilot_offered_at = now
        append_audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=None,
            action="chief.autopilot_offered",
            target_type="chief_detector",
            target_id=det.code,
            payload={"actor": "chief"},
        )
        for u in db.query(User).filter(
            User.tenant_id == tenant.id, User.role == UserRole.OWNER, User.is_active.is_(True)
        ):
            send_to_tenant(
                db,
                tenant.id,
                "The AI Executive can do one job by itself",
                f"It did this {tuning.AUTOPILOT_MIN_RUNS} times with your OK and it worked. Let it carry on "
                "without asking? (internal drafts only)",
                url="/dashboard/analyst",
                tag="chief",
                user_id=u.id,
            )
        out.append(det.code)
    return out
