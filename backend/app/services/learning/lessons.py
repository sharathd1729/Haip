"""Lessons memory (agent_lessons): what this business has PROVEN, fed back to the analyst (facts.lessons) and to the sales agent
(the concierge prompt's "PROVEN FOR THIS BUSINESS" block, at most ``brand_config.learning.max_lessons_in_prompt``, active only).

Written only from:
  * a KEPT experiment (from_experiment): the change, the metric, both arms' rates, the sample, the period
  * a significant finding seen in at least 2 of the last 3 weekly briefs at confidence >= 0.95 (from_findings)
Retired (never deleted) when a later test of the same change type is rolled back (contradicted_by) or the owner undoes the
change that proved it (retire_for). Lesson text is written by code from numbers, never by the model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.analyst import AgentExperiment, AgentLesson, AnalystReport

METRIC_LABELS = {"dm_to_lead": "people who gave a phone number", "guest_reply": "guests who kept talking",
                 "lead_to_quote": "leads who got a quote", "quote_to_won": "quotes that became bookings"}


def _pct(v: Optional[float]) -> str:
    return "?" if v is None else f"{round(v * 100)}%"


def from_experiment(db: Session, exp: AgentExperiment) -> Optional[AgentLesson]:
    m = exp.metrics or {}
    c, t = (m.get("control") or {}).get(exp.target_metric) or {}, (m.get("treatment") or {}).get(exp.target_metric) or {}
    n = int(c.get("n", 0)) + int(t.get("n", 0))
    text = (f"{exp.title}: {METRIC_LABELS.get(exp.target_metric, exp.target_metric)} {_pct(t.get('rate'))} with it vs "
            f"{_pct(c.get('rate'))} without ({n} conversations).")
    lesson = AgentLesson(tenant_id=exp.tenant_id, text=text[:600], metric=exp.target_metric, change_type=exp.change_type,
                         effect_size=round(float(t.get("rate") or 0) - float(c.get("rate") or 0), 4), sample=n,
                         period_start=exp.started_at.date() if exp.started_at else None,
                         period_end=(exp.ended_at or datetime.now(timezone.utc)).date(), source_experiment_id=exp.id)
    db.add(lesson)
    db.flush()
    return lesson


def _retire(rows: list[AgentLesson], reason: str) -> int:
    for r in rows:
        r.status, r.retired_reason, r.retired_at = "retired", reason[:300], datetime.now(timezone.utc)
    return len(rows)


def contradicted_by(db: Session, exp: AgentExperiment) -> int:
    rows = db.query(AgentLesson).filter_by(tenant_id=exp.tenant_id, change_type=exp.change_type, status="active").all()
    return _retire(rows, f"a later test ({exp.title}) did worse")


def retire_for(db: Session, exp: AgentExperiment, reason: str) -> int:
    return _retire(db.query(AgentLesson).filter_by(tenant_id=exp.tenant_id, source_experiment_id=exp.id, status="active").all(), reason)


def from_findings(db: Session, tenant_id: str, report: AnalystReport) -> list[AgentLesson]:
    if report.kind != "weekly_brief":
        return []
    recent = (db.query(AnalystReport).filter_by(tenant_id=tenant_id, kind="weekly_brief")
              .order_by(AnalystReport.period_start.desc()).limit(3).all())
    seen: dict[str, int] = {}
    label: dict[str, dict] = {}
    for r in recent:
        for f in (r.facts or {}).get("findings", []):
            if (f.get("confidence") or 0) >= 0.95:
                seen[f["id"]] = seen.get(f["id"], 0) + 1
                label[f["id"]] = f
    out = []
    existing = {t for (t,) in db.query(AgentLesson.text).filter_by(tenant_id=tenant_id, status="active").all()}
    for fid, n in seen.items():
        if n < 2:
            continue
        f = label[fid]
        text = f"Seen in {n} of the last {len(recent)} weekly briefs: {f['label'].lower()} went {f['direction']}."
        if text in existing:
            continue
        lesson = AgentLesson(tenant_id=tenant_id, text=text, metric=f["metric"], sample=0, source_report_id=report.id,
                             period_start=report.period_start, period_end=report.period_end)
        db.add(lesson)
        out.append(lesson)
    db.flush()
    return out


def active(db: Session, tenant_id: str, limit: int = 20) -> list[AgentLesson]:
    return (db.query(AgentLesson).filter_by(tenant_id=tenant_id, status="active")
            .order_by(AgentLesson.sample.desc(), AgentLesson.created_at.desc()).limit(limit).all())


def for_prompt(db: Session, tenant_id: str) -> list[dict]:
    """The analyst's context: every active lesson (text, metric, effect, sample)."""
    return [{"text": r.text, "metric": r.metric, "effect": r.effect_size, "sample": r.sample} for r in active(db, tenant_id)]


def prompt_lines(db: Session, tenant) -> list[str]:
    """The sales agent's "proven for this business" block: proven by a KEPT experiment only, at most N, active only."""
    from app.services.learning import settings as ls
    n = ls.get(tenant).max_lessons_in_prompt
    if n <= 0:
        return []
    return [r.text for r in active(db, tenant.id) if r.source_experiment_id][:n]


def view(r: AgentLesson) -> dict:
    return {"id": r.id, "text": r.text, "metric": r.metric, "change_type": r.change_type, "effect_size": r.effect_size,
            "sample": r.sample, "status": r.status, "retired_reason": r.retired_reason,
            "period": {"from": r.period_start.isoformat() if r.period_start else None,
                       "to": r.period_end.isoformat() if r.period_end else None},
            "source_experiment_id": r.source_experiment_id, "source_report_id": r.source_report_id}
