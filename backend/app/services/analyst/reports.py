"""Write, read and list analyst reports (analyst_reports). One row per (tenant, kind, period start): the scheduled tick is a
no-op once the period's report exists; a manual run (POST /analyst/reports/run) recomputes that period's row in place.

generate() is called from Celery only (analyst.run_report): facts in code, the brief via the router (brief.write, never
inline in a request), then the learning loop turns the brief's recommendations into change proposals (learning.proposals).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.analyst import AgentExperiment, AnalystReport
from app.services.analyst import brief as brief_svc
from app.services.analyst import facts as facts_svc
from app.services.analyst.periods import local_now, windows

log = structlog.get_logger()


def _lessons(db: Session, tenant_id: str) -> list[dict]:
    try:
        from app.services.learning import lessons
        return lessons.for_prompt(db, tenant_id)
    except Exception as exc:  # noqa: BLE001 -- lessons are context, never a reason to fail a report
        log.warning("analyst_lessons_unavailable", error=type(exc).__name__)
        return []


def last_followup(db: Session, tenant_id: str, kind: str, before: date) -> dict:
    """What the previous report of the same kind recommended, and what became of the changes started from it (code only)."""
    prev = (db.query(AnalystReport).filter(AnalystReport.tenant_id == tenant_id, AnalystReport.kind == kind,
                                           AnalystReport.period_start < before)
            .order_by(AnalystReport.period_start.desc()).first())
    if prev is None:
        return {}
    recs = (prev.brief or {}).get("recommendations") or []
    exps = db.query(AgentExperiment).filter(AgentExperiment.tenant_id == tenant_id,
                                            AgentExperiment.source_report_id == prev.id).all()
    by = {s: sum(1 for e in exps if e.status == s) for s in ("running", "kept", "rolled_back", "stopped", "awaiting_approval",
                                                               "bench_failed", "rejected")}
    summary = f"Last {facts_svc.KIND_LABELS[kind].lower()} made {len(recs)} recommendations"
    if exps:
        summary += "; changes from it: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in by.items() if n)
    return {"report_id": prev.id, "period": {"from": prev.period_start.isoformat(), "to": prev.period_end.isoformat()},
            "recommendations": [r.get("action") for r in recs][:6], "experiments": by, "summary": summary + "."}


def generate(db: Session, tenant, kind: str, *, today: Optional[date] = None, use_llm: bool = True,
             actor_id: Optional[str] = None, force: bool = False) -> AnalystReport:
    today = today or local_now().date()
    cur, _p, _b = windows(kind, today)
    row = db.query(AnalystReport).filter_by(tenant_id=tenant.id, kind=kind, period_start=cur.d_from).first()
    if row is not None and not force:
        return row
    facts = facts_svc.build(db, tenant, kind, today, lessons=_lessons(db, tenant.id),
                            last_followup=last_followup(db, tenant.id, kind, cur.d_from))
    written = brief_svc.write(facts, use_llm=use_llm)
    if row is None:
        row = AnalystReport(tenant_id=tenant.id, kind=kind, period_start=cur.d_from, period_end=cur.d_to, created_by=actor_id)
        db.add(row)
    row.facts, row.brief, row.brief_source = facts, written["brief"], written["source"]
    row.validation = {**written["validation"], "generated_at": datetime.now(timezone.utc).isoformat()}
    row.model, row.prompt_version, row.status = written["model"], written["prompt_version"], "ready"
    db.flush()
    try:
        from app.services.learning import proposals
        proposals.from_report(db, tenant, row)
        from app.services.learning import lessons
        lessons.from_findings(db, tenant.id, row)
    except Exception as exc:  # noqa: BLE001 -- a proposal problem never loses the report
        log.warning("analyst_proposals_failed", tenant_id=tenant.id, report_id=row.id, error=type(exc).__name__)
    db.commit()
    log.info("analyst_report_written", tenant_id=tenant.id, kind=kind, period_start=cur.d_from.isoformat(),
             source=written["source"], findings=len(facts["findings"]))
    return row


def assign_recommendation(db: Session, report: AnalystReport, index: int, user_id: str, actor) -> dict:
    """Give one recommendation to a team member: kept on the report (``delivery.actions``), pushed to them, audited."""
    from app.core.audit import append_audit
    from app.models.user import User
    recs = (report.brief or {}).get("recommendations") or []
    if not 0 <= index < len(recs):
        raise LookupError("recommendation not found")
    person = db.query(User).filter_by(id=user_id, tenant_id=report.tenant_id, is_active=True, is_deleted=False).first()
    if person is None:
        raise LookupError("person not found")
    actions = dict((report.delivery or {}).get("actions") or {})
    actions[str(index)] = {"assigned_to": user_id, "name": person.name, "by": actor.id, "at": datetime.now(timezone.utc).isoformat()}
    report.delivery = {**(report.delivery or {}), "actions": actions}
    append_audit(db, tenant_id=report.tenant_id, actor_user_id=actor.id, action="analyst.recommendation_assigned",
                 target_type="analyst_report", target_id=report.id, payload={"index": index, "to": user_id})
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(db, report.tenant_id, title="A recommendation for you", body=str(recs[index].get("action"))[:140],
                       url="/dashboard/analyst", tag=f"analyst-{report.id}-{index}", user_id=user_id)
    except Exception as exc:  # noqa: BLE001 -- push is best-effort
        log.warning("analyst_assign_push_failed", report_id=report.id, error=type(exc).__name__)
    return actions[str(index)]


def summary_out(r: AnalystReport) -> dict:
    b = r.brief or {}
    return {"id": r.id, "kind": r.kind, "period": {"from": r.period_start.isoformat(), "to": r.period_end.isoformat()},
            "headline": b.get("headline"), "source": r.brief_source, "created_at": r.created_at.isoformat() if r.created_at else None,
            "health": [{"key": c["key"], "label": c["label"], "status": c["status"]} for c in (r.facts or {}).get("health", [])]}


def view(r: AnalystReport) -> dict:
    return {**summary_out(r), "brief": r.brief or {}, "facts": r.facts or {}, "validation": r.validation or {},
            "model": r.model, "prompt_version": r.prompt_version, "followups": r.followups or [],
            "delivery": r.delivery or {}}


def list_reports(db: Session, tenant_id: str, kind: Optional[str] = None, limit: int = 30) -> list[dict]:
    q = db.query(AnalystReport).filter(AnalystReport.tenant_id == tenant_id)
    if kind:
        q = q.filter(AnalystReport.kind == kind)
    else:                       # the Marketing Studio's weekly Insights rows live in the same table; they have their own page
        q = q.filter(AnalystReport.kind != "marketing_insights")
    return [summary_out(r) for r in q.order_by(AnalystReport.period_start.desc(), AnalystReport.created_at.desc()).limit(limit).all()]


def get(db: Session, tenant_id: str, report_id: str) -> Optional[AnalystReport]:
    return db.query(AnalystReport).filter_by(tenant_id=tenant_id, id=report_id).first()
