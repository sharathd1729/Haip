"""The AI Executive's findings, kept in the ``insights`` table (one store with the older insight detectors; migration 185).

  run(db, tenant, cadence)   run the catalogue's detectors for one workspace: a hit is upserted on (code, target), a detector
                             that ran and did not fire resolves its open rows; a detector that FAILS changes nothing
  dismiss(...)               the founder's "not now" / "wrong" / ...: hidden, snoozed 7 days, reason kept (learning, E4)
  home(...)                  the Executive page: open findings by role (older insights included), the latest daily pulse
  brief_block(...)           the Executive lines added to the analyst's facts

Audited: ``chief.finding_raised`` / ``chief.finding_resolved`` (actor system) and ``chief.finding_dismissed``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.insight import Insight
from app.schemas.chief import ROLE_LABELS
from app.services.chief import catalogue, tuning
from app.services.chief import settings as chief_settings
from app.services.chief.detectors import Ctx

log = structlog.get_logger()

SNOOZE = timedelta(days=7)
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _open(db: Session, tenant_id: str, code: str):
    return db.query(Insight).filter(
        Insight.tenant_id == tenant_id,
        Insight.category_code == code,
        Insight.is_dismissed.is_(False),
        Insight.is_auto_resolved.is_(False),
    )


def _snoozed(db: Session, tenant_id: str, code: str, target_id: str | None, now: datetime) -> bool:
    rows = (
        db.query(Insight.snoozed_until)
        .filter(
            Insight.tenant_id == tenant_id,
            Insight.category_code == code,
            Insight.target_id.is_(None) if target_id is None else Insight.target_id == target_id,
            Insight.is_dismissed.is_(True),
            Insight.snoozed_until.isnot(None),
        )
        .all()
    )
    return any(_aware(s) > now for (s,) in rows)


def _audit(db: Session, tenant_id: str, action: str, row: Insight, **payload) -> None:
    append_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=None,
        action=action,
        target_type="insight",
        target_id=row.id,
        payload={"actor": "chief", "code": row.category_code, **payload},
    )


def _upsert(db: Session, tenant_id: str, det: catalogue.Detector, hit: dict, now: datetime) -> Insight | None:
    target = hit.get("target_id")
    q = _open(db, tenant_id, det.code)
    row = q.filter(Insight.target_id.is_(None) if target is None else Insight.target_id == target).first()
    if row is None:
        if _snoozed(db, tenant_id, det.code, target, now):
            return None
        row = Insight(
            tenant_id=tenant_id,
            category_code=det.code,
            target_id=target,
            category=det.category,
            role=det.role,
            first_seen_at=now,
            title=hit["title"],
        )
        db.add(row)
        db.flush()
        _audit(db, tenant_id, "chief.finding_raised", row, severity=hit["severity"], numbers=hit["numbers"])
    row.severity, row.title, row.body = hit["severity"], hit["title"], hit["body"]
    row.numbers, row.evidence = hit["numbers"], hit["evidence"]
    row.cta_label, row.cta_href = hit.get("cta_label"), hit.get("cta_href")
    row.last_seen_at = row.updated_at = now
    return row


def _resolve(db: Session, tenant_id: str, code: str, keep: set, now: datetime) -> int:
    n = 0
    for row in _open(db, tenant_id, code).all():
        if row.target_id in keep:
            continue
        row.is_auto_resolved, row.auto_resolved_at = True, now
        _audit(db, tenant_id, "chief.finding_resolved", row)
        n += 1
    return n


def run(db: Session, tenant, cadence: str = "urgent", now: datetime | None = None) -> dict:
    """Run the detectors due in this cadence. Returns counts; the caller commits."""
    cfg = chief_settings.get(tenant)
    out = {"ran": 0, "open": 0, "raised": 0, "resolved": 0, "failed": [], "skipped": not cfg.enabled}
    if not cfg.enabled:
        return out
    now = now or datetime.now(UTC)
    ctx = Ctx(db, tenant, now)
    learned = tuning.all_for(db, tenant.id)
    for det in catalogue.CATALOGUE:
        if not catalogue.runs_in(det, cadence) or det.code in cfg.detectors_off or det.role in cfg.roles_off:
            continue
        if tuning.muted(learned.get(det.code), now):  # paused for 30 days after the owner kept turning it down
            out.setdefault("muted", []).append(det.code)
            continue
        try:
            with db.begin_nested():
                hits = det.rule(ctx)
                before = _open(db, tenant.id, det.code).count()
                rows = [r for r in (_upsert(db, tenant.id, det, h, now) for h in hits) if r is not None]
                out["resolved"] += _resolve(db, tenant.id, det.code, {r.target_id for r in rows}, now)
                out["raised"] += max(0, len(rows) - before)
                out["open"] += len(rows)
                out["ran"] += 1
        except Exception as exc:  # noqa: BLE001 -- one broken rule never stops the others, nor resolves its findings
            out["failed"].append(det.code)
            log.warning(
                "chief_detector_failed", tenant_id=tenant.id, code=det.code, error=f"{type(exc).__name__}: {exc}"
            )
    return out


# ── reading ───────────────────────────────────────────────────────────────────────────────────────────────────


def view(row: Insight, learned: dict | None = None) -> dict:
    """``learned`` = tuning.all_for(...): adds what the Executive learned about this detector (confidence, threshold, why)."""
    det = catalogue.BY_CODE.get(row.category_code)
    role = catalogue.role_of(row.category_code, row.role)
    exp = row.explanation if isinstance(row.explanation, dict) else {}
    status = "dismissed" if row.is_dismissed else "resolved" if row.is_auto_resolved else "open"
    return {
        "id": row.id,
        "code": row.category_code,
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "severity": row.severity,
        "title": row.title,
        "body": row.body,
        "why": exp.get("why") or row.body,
        "next_step": exp.get("next_step") or (det.next_step if det else row.cta_label),
        "explained_by": exp.get("source") or "rule",
        "numbers": row.numbers or {},
        "evidence": row.evidence or [],
        "cta_label": row.cta_label,
        "cta_href": row.cta_href,
        "status": status,
        "first_seen_at": row.first_seen_at or row.created_at,
        "last_seen_at": row.last_seen_at or row.updated_at,
        "resolved_at": row.auto_resolved_at,
        "dismiss_reason": row.dismiss_reason,
        "snoozed_until": row.snoozed_until,
        "learning": tuning.view(row.category_code, (learned or {}).get(row.category_code))
        if learned is not None
        else None,
    }


def _sorted(rows: list[Insight], learned: dict | None = None) -> list[Insight]:
    """Worst first; equal severity: the detector whose fixes the owner approves and that work (tuning.confidence)."""
    learned = learned or {}
    return sorted(
        rows,
        key=lambda r: (
            SEVERITY_ORDER.get(r.severity, 9),
            -tuning.confidence(learned.get(r.category_code)),
            -(_aware(r.last_seen_at or r.updated_at) or datetime.min.replace(tzinfo=UTC)).timestamp(),
        ),
    )


def list_findings(
    db: Session, tenant_id: str, *, status: str = "open", role: str | None = None, limit: int = 100
) -> list[dict]:
    q = db.query(Insight).filter(Insight.tenant_id == tenant_id)
    if status == "open":
        q = q.filter(Insight.is_dismissed.is_(False), Insight.is_auto_resolved.is_(False))
    elif status == "resolved":
        q = q.filter(Insight.is_auto_resolved.is_(True))
    else:
        q = q.filter(Insight.is_dismissed.is_(True))
    rows = q.order_by(Insight.updated_at.desc()).limit(500).all()
    learned = tuning.all_for(db, tenant_id)
    out = [view(r, learned) for r in _sorted(rows, learned)]
    return [f for f in out if role is None or f["role"] == role][:limit]


def get(db: Session, tenant_id: str, finding_id: str) -> Insight | None:
    return db.query(Insight).filter(Insight.id == finding_id, Insight.tenant_id == tenant_id).first()


def dismiss(
    db: Session,
    tenant_id: str,
    row: Insight,
    user_id: str,
    reason: str,
    note: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    row.is_dismissed, row.dismissed_by, row.dismissed_at = True, user_id, now
    row.dismiss_reason, row.snoozed_until = reason, now + SNOOZE
    append_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action="chief.finding_dismissed",
        target_type="insight",
        target_id=row.id,
        payload={"code": row.category_code, "reason": reason, **({"note": note} if note else {})},
    )
    tuning.on_decision(db, tenant_id, row.category_code, "dismissed", reason)
    return view(row, tuning.all_for(db, tenant_id))


def home(db: Session, tenant) -> dict:
    cfg = chief_settings.get(tenant)
    open_ = list_findings(db, tenant.id, status="open", limit=500)
    week = datetime.now(UTC) - timedelta(days=7)
    resolved = (
        db.query(Insight)
        .filter(Insight.tenant_id == tenant.id, Insight.is_auto_resolved.is_(True), Insight.auto_resolved_at >= week)
        .count()
    )
    roles = []
    for key, label in ROLE_LABELS.items():
        mine = [f for f in open_ if f["role"] == key]
        if mine:
            roles.append({"key": key, "label": label, "findings": mine})
    from app.services.analyst import reports

    pulse = reports.list_reports(db, tenant.id, "daily_pulse", 1)
    return {
        "settings": cfg.model_dump(),
        "counts": {s: sum(1 for f in open_ if f["severity"] == s) for s in SEVERITY_ORDER}
        | {"open": len(open_), "resolved_7d": resolved},
        "roles": roles,
        "top": open_[:3],
        "brief": pulse[0] if pulse else None,
        "last_checked_at": max(
            (f["last_seen_at"] for f in open_ if f["code"] in catalogue.BY_CODE and f["last_seen_at"]),
            default=None,
            key=lambda d: _aware(d),
        ),
        **_proposals_block(db, tenant, week),
    }


def _proposals_block(db: Session, tenant, since: datetime) -> dict:
    """E2: plans waiting for the owner, everything else that needs a yes (one inbox), and what was done this week."""
    from app.models.chief import ChiefProposal
    from app.services.chief import approvals

    rows = (
        db.query(ChiefProposal)
        .filter(ChiefProposal.tenant_id == tenant.id)
        .filter(
            (ChiefProposal.status.in_(("awaiting_approval", "approved", "executing", "waiting")))
            | (ChiefProposal.updated_at >= since)
        )
        .order_by(ChiefProposal.created_at.desc())
        .limit(100)
        .all()
    )
    inbox = approvals.pending(db, tenant)
    return {
        "proposals": [approvals.view(p) for p in rows if p.status == "awaiting_approval"],
        "activity": [approvals.view(p) for p in rows if p.status != "awaiting_approval"][:20],
        "approvals": [a for a in inbox if a["source"] != "executive"],
    }


def brief_block(db: Session, tenant) -> dict | None:
    """For the analyst facts: open Executive findings by role and the top 5 (titles carry counts only, never names)."""
    if not chief_settings.get(tenant).enabled:
        return None
    open_ = list_findings(db, tenant.id, status="open", limit=500)
    by_role: dict[str, int] = {}
    for f in open_:
        by_role[f["role_label"]] = by_role.get(f["role_label"], 0) + 1
    return {
        "open": len(open_),
        "by_role": by_role,
        "top": [{"role": f["role_label"], "severity": f["severity"], "title": f["title"]} for f in open_[:5]],
        "worked_7d": _outcomes_since(db, tenant.id, datetime.now(UTC) - timedelta(days=7)),
    }


def _outcomes_since(db: Session, tenant_id: str, since: datetime) -> dict:
    """E4 "what worked": outcome verdicts recorded since then (services/chief/outcomes.py)."""
    from app.models.chief import ChiefProposal

    counts = {"improved": 0, "no_change": 0, "worse": 0}
    for (outcome,) in db.query(ChiefProposal.outcome).filter(
        ChiefProposal.tenant_id == tenant_id, ChiefProposal.status == "done", ChiefProposal.updated_at >= since
    ):
        v = (outcome or {}).get("verdict")
        if v in counts:
            counts[v] += 1
    return counts
