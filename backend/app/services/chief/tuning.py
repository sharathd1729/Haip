"""How the AI Executive learns, per workspace and detector (E4; docs/ai/AI_EXECUTIVE_PLAN.md section 4). Only WHEN and HOW
OFTEN a detector raises and proposes; never what an action does, never across risk tiers. Every change is audited
``chief.tuning_changed`` with before / after / reason, and the owner can reset a detector to its defaults.

Ladders (LADDERS): the thresholds a detector may use, set in code; index 1 is the catalogue default, 0 more sensitive,
higher = stricter. A detector without a ladder can only be muted.

  rejected 3 times in a row, or > 70% turned down of >= 5 decisions   -> one step stricter + muted 30 days
  "not now"                                                           -> nothing (it only snoozes)
  dismissed                                                           -> counts half a rejection
  3 approvals in a row that worked (outcome improved)                 -> one step more sensitive (never below index 0)
  outcome worse                                                       -> one step stricter, and autopilot is switched off

Confidence = Beta mean of approvals x Beta mean of success: (approved + 1) / (decisions + 2) x (improved + 1) /
(checked + 2). Findings and proposals of equal severity are shown highest confidence first.

Autopilot (AUTOPILOT_MIN_RUNS = 5): only plans whose every step is R1 (internal drafts). Eligible after 5 done proposals in
60 days, every outcome improved or no_change, none worse; then OFFERED to the owners. It turns on only when an owner opts
in (PUT /chief/autopilot/{code}); that owner is the approver of record. A worse outcome switches it off again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.chief import ChiefDetectorTuning, ChiefProposal

LADDERS: dict[str, tuple] = {
    "SA1": (2, 3, 5, 8),  # people waiting past the reply target
    "SA2": (3, 5, 8, 12),  # leads nobody owns
    "SA8": (2, 3, 5, 8),  # leads at risk
    "SA9": (10, 15, 30, 50),  # autopilot suggestions nobody applied
    "CO2": (5, 10, 20, 40),  # AI drafts expired in a day
    "MK1": (5, 10, 20, 40),  # comments on one post in a day
    "MK2": (1000, 2000, 5000, 10000),  # rupees spent with no lead
    "API1": (5, 10, 25, 50),  # webhook failures in a row
}
# Which number says whether the problem got better, and which way is better (default: the first number, lower).
PRIMARY: dict[str, tuple[str, str]] = {
    "WB1": ("enquiries", "higher"),
    "OW3": ("last_7_days", "higher"),
    "OW3B": ("last_7_days", "higher"),
    "MK4": ("last_14_days", "higher"),
}
DEFAULT_STEP = 1
MUTE = timedelta(days=30)
AUTOPILOT_MIN_RUNS = 5
AUTOPILOT_WINDOW = timedelta(days=60)
CHANGE = 0.2  # a primary number has to move 20% to count as better / worse


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def get(db: Session, tenant_id: str, code: str) -> ChiefDetectorTuning | None:
    return db.query(ChiefDetectorTuning).filter_by(tenant_id=tenant_id, code=code).first()


def all_for(db: Session, tenant_id: str) -> dict[str, ChiefDetectorTuning]:
    return {t.code: t for t in db.query(ChiefDetectorTuning).filter_by(tenant_id=tenant_id).all()}


def _row(db: Session, tenant_id: str, code: str) -> ChiefDetectorTuning:
    t = get(db, tenant_id, code)
    if t is None:
        t = ChiefDetectorTuning(
            tenant_id=tenant_id,
            code=code,
            step=DEFAULT_STEP,
            approved=0,
            rejected=0,
            dismissed=0,
            improved=0,
            no_change=0,
            worse=0,
            rejections_in_row=0,
            wins_in_row=0,
        )
        db.add(t)
        db.flush()
    return t


def threshold(code: str, t: ChiefDetectorTuning | None) -> float | None:
    ladder = LADDERS.get(code)
    if not ladder:
        return None
    step = DEFAULT_STEP if t is None else max(0, min(t.step, len(ladder) - 1))
    return ladder[step]


def muted(t: ChiefDetectorTuning | None, now: datetime | None = None) -> bool:
    return bool(t and t.muted_until and _aware(t.muted_until) > (now or _now()))


def confidence(t: ChiefDetectorTuning | None) -> float:
    if t is None:
        return 0.25  # the prior: (0 + 1) / 2 x (0 + 1) / 2
    decided = t.approved + t.rejected + t.dismissed * 0.5
    checked = t.improved + t.no_change + t.worse
    return round((t.approved + 1) / (decided + 2) * (t.improved + 1) / (checked + 2), 4)


def _move(db: Session, t: ChiefDetectorTuning, delta: int, reason: str, *, mute: bool = False) -> None:
    ladder = LADDERS.get(t.code)
    before = {"step": t.step, "muted_until": t.muted_until.isoformat() if t.muted_until else None}
    if ladder:
        t.step = max(0, min(t.step + delta, len(ladder) - 1))
    if mute:
        t.muted_until = _now() + MUTE
    t.last_reason = reason
    after = {"step": t.step, "muted_until": t.muted_until.isoformat() if t.muted_until else None}
    if before != after:
        append_audit(
            db,
            tenant_id=t.tenant_id,
            actor_user_id=None,
            action="chief.tuning_changed",
            target_type="chief_detector",
            target_id=t.code,
            payload={
                "actor": "chief",
                "before": before,
                "after": after,
                "reason": reason,
                "threshold": threshold(t.code, t),
            },
        )


def on_decision(
    db: Session, tenant_id: str, code: str, decision: str, reason: str | None = None
) -> ChiefDetectorTuning:
    """decision approved | rejected | dismissed (reason not_now = a snooze, not a judgement)."""
    t = _row(db, tenant_id, code)
    if reason == "not_now":
        return t
    if decision == "approved":
        t.approved += 1
        t.rejections_in_row = 0
        return t
    if decision == "rejected":
        t.rejected += 1
        t.rejections_in_row += 1
    else:
        t.dismissed += 1
    decided = t.approved + t.rejected + t.dismissed * 0.5
    turned_down = t.rejected + t.dismissed * 0.5
    if t.rejections_in_row >= 3:
        _move(
            db,
            t,
            +1,
            f"Raised and paused for 30 days after you turned it down {t.rejections_in_row} times in a row.",
            mute=True,
        )
        t.rejections_in_row = 0
    elif decided >= 5 and turned_down / decided > 0.7:
        _move(
            db,
            t,
            +1,
            f"Raised and paused for 30 days: you turned down {round(turned_down)} of {round(decided)}.",
            mute=True,
        )
    return t


def on_outcome(db: Session, tenant_id: str, code: str, verdict: str) -> ChiefDetectorTuning:
    """verdict improved | no_change | worse | too_few."""
    t = _row(db, tenant_id, code)
    if verdict == "improved":
        t.improved += 1
        t.wins_in_row += 1
        if t.wins_in_row >= 3:
            _move(db, t, -1, "Made more sensitive: the last 3 fixes you approved all worked.")
            t.wins_in_row = 0
    elif verdict == "no_change":
        t.no_change += 1
        t.wins_in_row = 0
    elif verdict == "worse":
        t.worse += 1
        t.wins_in_row = 0
        _move(db, t, +1, "Raised: after the last fix the number got worse.")
        if t.autopilot_by:
            stop_autopilot(db, t, "Autopilot switched off: after the last fix the number got worse.")
    return t


def verdict(code: str, baseline: dict, current: dict, resolved: bool) -> str:
    if resolved:
        return "improved"
    key, better = PRIMARY.get(code, (next(iter(baseline), None), "lower"))
    if key is None or not isinstance(baseline.get(key), (int, float)) or not isinstance(current.get(key), (int, float)):
        return "too_few"
    before, now = float(baseline[key]), float(current[key])
    if before == 0:
        return "too_few"
    change = (now - before) / abs(before)
    if better == "higher":
        change = -change
    return "improved" if change <= -CHANGE else "worse" if change >= CHANGE else "no_change"


# ── autopilot ────────────────────────────────────────────────────────────────────────────────────────────────


def all_r1(steps: list[dict]) -> bool:
    return bool(steps) and all(s.get("tier") == "R1" for s in steps)


def eligible(db: Session, tenant_id: str, code: str, now: datetime | None = None) -> bool:
    now = now or _now()
    rows = (
        db.query(ChiefProposal)
        .filter(
            ChiefProposal.tenant_id == tenant_id,
            ChiefProposal.code == code,
            ChiefProposal.status == "done",
            ChiefProposal.finished_at >= now - AUTOPILOT_WINDOW,
        )
        .all()
    )
    if len(rows) < AUTOPILOT_MIN_RUNS or not all(p.risk_tier == "R1" and all_r1(p.steps) for p in rows):
        return False
    verdicts = [(p.outcome or {}).get("verdict") for p in rows]
    return all(v in ("improved", "no_change") for v in verdicts) and "worse" not in verdicts


def start_autopilot(db: Session, tenant_id: str, code: str, user_id: str) -> ChiefDetectorTuning:
    if not eligible(db, tenant_id, code):
        raise ValueError(
            "Not yet: autopilot needs 5 fixes you approved in 60 days that all worked, for internal drafts only."
        )
    t = _row(db, tenant_id, code)
    t.autopilot_by, t.autopilot_at = user_id, _now()
    append_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action="chief.autopilot_on",
        target_type="chief_detector",
        target_id=code,
        payload={"code": code},
    )
    return t


def stop_autopilot(db: Session, t: ChiefDetectorTuning, reason: str, user_id: str | None = None) -> None:
    t.autopilot_by, t.autopilot_at, t.last_reason = None, None, reason
    append_audit(
        db,
        tenant_id=t.tenant_id,
        actor_user_id=user_id,
        action="chief.autopilot_off",
        target_type="chief_detector",
        target_id=t.code,
        payload={"reason": reason, **({} if user_id else {"actor": "chief"})},
    )


def reset(db: Session, tenant_id: str, code: str, user_id: str) -> None:
    t = get(db, tenant_id, code)
    if t is None:
        return
    append_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action="chief.tuning_reset",
        target_type="chief_detector",
        target_id=code,
        payload={"before": view(code, t)},
    )
    db.delete(t)


def history_text(t: ChiefDetectorTuning | None) -> str | None:
    if t is None:
        return None
    decided = t.approved + t.rejected
    parts = []
    if decided:
        parts.append(f"You approved {t.approved} of {decided} like this")
    checked = t.improved + t.no_change + t.worse
    if checked:
        parts.append(f"{t.improved} of {checked} worked")
    return ("; ".join(parts) + ".") if parts else None


def view(code: str, t: ChiefDetectorTuning | None, now: datetime | None = None) -> dict:
    return {
        "code": code,
        "confidence": confidence(t),
        "threshold": threshold(code, t),
        "default_threshold": threshold(code, None),
        "step": t.step if t else DEFAULT_STEP,
        "muted": muted(t, now),
        "muted_until": t.muted_until if t else None,
        "reason": t.last_reason if t else None,
        "history": history_text(t),
        "counts": {
            k: getattr(t, k) if t else 0
            for k in ("approved", "rejected", "dismissed", "improved", "no_change", "worse")
        },
        "autopilot": bool(t and t.autopilot_by),
        "autopilot_offered": bool(t and t.autopilot_offered_at),
    }
