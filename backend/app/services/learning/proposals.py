"""Turn a report into change proposals (called by analyst.reports.generate, in Celery).

Code decides WHICH catalogue changes to propose, from the health checks and findings (never the model's free text); the brief's
recommendations may only point at a type (``change_proposal``) that the rules below can fill with a concrete, validated diff.
Every proposal then goes through experiments.propose (catalogue guardrails, autonomy check, bench gate). One open proposal per
change type; a type the owner turned down is not proposed again for 14 days.

  communication amber/red, or dm_to_lead down        playbook_wording: an opening line that asks for the WhatsApp number
                                                     and says why (only when the playbook's opening line differs)
  contact_to_proposal / lead_to_contact down         early_package_share
  pricing amber/red                                  kit_before_discount (when the playbook does not already say it)
  follow_ups amber/red, or proposal_to_sold down     followup_timing: first quote follow-up after 3 h (code default 6 h)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.models.analyst import AgentExperiment

log = structlog.get_logger()

OPENING_LINE = ("Happy to help you plan this trip! Share your WhatsApp number and travel dates and we will send the full "
                "day plan there.")
OPEN = ("proposed", "awaiting_approval", "running")
COOL_OFF = timedelta(days=14)


def _blocked(db: Session, tenant_id: str, change_type: str) -> bool:
    rows = db.query(AgentExperiment.status, AgentExperiment.updated_at).filter_by(tenant_id=tenant_id, change_type=change_type).all()
    since = datetime.now(timezone.utc) - COOL_OFF
    from app.services.kpi_metrics import as_datetime
    return any(s in OPEN or (s == "rejected" and as_datetime(u) >= since) for s, u in rows)


def candidates(tenant, facts: dict, brief: dict) -> list[tuple[str, dict, str]]:
    """[(change_type, diff, why)] in priority order, from the facts (and the brief's pointers)."""
    from app.services import sales_playbook
    health = {c["key"]: c["status"] for c in facts.get("health", [])}
    down = {f["metric"] for f in facts.get("findings", []) if f.get("direction") == "down" and f.get("better") == "up"}
    pointed = {r.get("change_proposal") for r in (brief or {}).get("recommendations", []) if r.get("change_proposal")}
    pb = sales_playbook.get(tenant)
    out = []
    if health.get("communication") in ("amber", "red") or "dm_to_lead" in down or "playbook_wording" in pointed:
        if pb.opening_line.strip() != OPENING_LINE:
            out.append(("playbook_wording", {"field": "opening_line", "value": OPENING_LINE},
                        "fewer people who write in give a phone number"))
    if {"contact_to_proposal", "lead_to_contact"} & down or "early_package_share" in pointed:
        out.append(("early_package_share", {}, "fewer contacted enquiries get a proposal"))
    if health.get("pricing") in ("amber", "red") or "kit_before_discount" in pointed:
        if not pb.add_value_before_discount:
            out.append(("kit_before_discount", {"segments": []}, "price objections are high"))
    if health.get("follow_ups") in ("amber", "red") or "proposal_to_sold" in down or "followup_timing" in pointed:
        out.append(("followup_timing", {"playbook": "proposal_followup", "first_hours": 3}, "proposals are not converting"))
    return out


def from_report(db: Session, tenant, report) -> list[str]:
    from app.services.learning import experiments
    made = []
    for change_type, diff, why in candidates(tenant, report.facts or {}, report.brief or {}):
        if _blocked(db, tenant.id, change_type):
            continue
        try:
            exp = experiments.propose(db, tenant, change_type, diff, source_report_id=report.id,
                                      rationale={"why": why, "report_id": report.id,
                                                 "findings": [f["id"] for f in (report.facts or {}).get("findings", [])][:5],
                                                 "health": {c["key"]: c["status"] for c in (report.facts or {}).get("health", [])}})
            made.append(exp.id)
        except experiments.ExperimentError as exc:
            log.info("learning_proposal_refused", tenant_id=tenant.id, change_type=change_type, code=exc.code)
    return made
