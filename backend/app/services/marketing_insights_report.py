"""Write and read the weekly Insights report (studio plan phase 1). Facts come from marketing_insights (code only); the
AI (router task `marketing_insights`, prompt marketing-insights-v1) writes a headline and one plain-English line per
verdict item. analyst.grounding drops any sentence whose number is not in the facts; a failed or unusable AI answer
leaves the deterministic text. Called from Celery only (`marketing_insights.weekly_tenant`), never in a request.
"""
import json
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.prompt_versions import get_version
from app.core.tenant_tz import get_tenant_now
from app.models.analyst import AnalystReport
from app.models.tenant import Tenant
from app.services import marketing_ai_service as ai
from app.services import marketing_insights as insights
from app.services import usage_service
from app.services.analyst import grounding
from app.services.marketing_prompts import _schema

log = structlog.get_logger()

TASK = "marketing_insights"
SECTIONS = ("wins", "problems", "actions")

SYSTEM = """You explain a hospitality business's weekly marketing report to its owner in plain English.
The FACTS (JSON) were computed by code. Write:
- headline: one sentence, the most important thing about last week.
- explain.wins / explain.problems / explain.actions: for each verdict item, in the same order, ONE short sentence on why it
  matters or what to do next.
Rules: use only numbers that appear in the facts, written the same way; never invent a number, percentage or date.
Keep each item's confidence word (Strong / Early signal / Not enough data) honest: never call an "Early signal" proven.
When data is thin, say so. No jargon, no hype, no emojis."""


class _Explain(BaseModel):
    wins: list[str] = Field(default_factory=list, max_length=3)
    problems: list[str] = Field(default_factory=list, max_length=3)
    actions: list[str] = Field(default_factory=list, max_length=3)


class InsightsText(BaseModel):
    headline: str = Field(max_length=300)
    explain: _Explain = Field(default_factory=_Explain)


def tool() -> dict:
    return {"name": "submit_insights", "description": "Return the headline and explanations.",
            "input_schema": _schema(InsightsText)}


def deterministic(facts: dict) -> dict:
    v = facts["verdict"]
    f = facts["funnel"]
    headline = (v["wins"][0]["text"] if v["wins"] else v["problems"][0]["text"] if v["problems"] else
                f"Last week: Rs {f['ads']['spend']} on ads, {int(f['ads']['chats'] + f['organic']['chats'])} chats traced.")
    return {"headline": headline, **{s: [{**i, "explanation": None} for i in v[s]] for s in SECTIONS}}


def _compact(facts: dict) -> str:
    keep = {k: facts[k] for k in ("period", "funnel", "verdict", "next_plan", "context", "fatigue")}
    keep["ads"] = facts["ads"][:5]
    keep["posts"] = [{k: p.get(k) for k in ("format", "reach", "reach_vs_median", "engagement_vs_median", "confidence")}
                     for p in facts["posts"]][:10]
    return json.dumps(keep, default=str, ensure_ascii=False)[:12000]


def write(db: Session, tenant_id: str, facts: dict, *, use_llm: bool = True) -> dict:
    """{brief, source, validation, model}. Never raises: provider trouble = the deterministic text."""
    brief = deterministic(facts)
    if not use_llm:
        return {"brief": brief, "source": "deterministic", "validation": {"llm": "skipped"}, "model": None}
    try:
        data, raw, provider = ai._call(TASK, tenant_id, SYSTEM, f"FACTS:\n{_compact(facts)}", tool())
        usage_service.record_llm(db, tenant_id, ai.MODULE, raw, provider=provider, ref_type="marketing_insights",
                                 ref_id=facts["period"]["from"])
        text = InsightsText.model_validate(data)
    except Exception as exc:  # noqa: BLE001 -- transient or not, the deterministic report stands
        log.warning("marketing_insights_llm_failed", tenant_id=tenant_id, error=type(exc).__name__)
        return {"brief": brief, "source": "deterministic", "validation": {"llm": f"failed: {type(exc).__name__}"},
                "model": None}
    allowed, dropped = grounding.allowed_numbers(facts), []
    headline = grounding.clean_text(text.headline, allowed, "headline", dropped)
    if headline:
        brief["headline"] = headline
    for s in SECTIONS:
        lines = getattr(text.explain, s)
        for i, item in enumerate(brief[s]):
            if i < len(lines):
                item["explanation"] = grounding.clean_text(lines[i], allowed, f"{s}[{i}]", dropped) or None
    return {"brief": brief, "source": "llm", "validation": {"llm": "ok", "dropped": dropped[:20]}, "model": raw.get("model")}


def generate(db: Session, tenant: Tenant, *, today: Optional[date] = None, use_llm: bool = True,
             force: bool = False, actor_id: Optional[str] = None) -> AnalystReport:
    today = today or get_tenant_now(tenant).date()
    since, until = insights.last_week(today)
    row = db.query(AnalystReport).filter_by(tenant_id=tenant.id, kind=insights.KIND, period_start=since).first()
    if row is not None and not force:
        return row
    facts = insights.facts(db, tenant, today)
    written = write(db, tenant.id, facts, use_llm=use_llm)
    if row is None:
        row = AnalystReport(tenant_id=tenant.id, kind=insights.KIND, period_start=since, period_end=until, created_by=actor_id)
        db.add(row)
    row.facts, row.brief, row.brief_source = facts, written["brief"], written["source"]
    row.validation = {**written["validation"], "generated_at": datetime.now(timezone.utc).isoformat()}
    row.model, row.prompt_version, row.status = written["model"], get_version(TASK), "ready"
    db.flush()
    return row


def notify(db: Session, tenant_id: str, row: AnalystReport) -> None:
    """Push to the workspace's devices once per report (best-effort)."""
    if (row.delivery or {}).get("pushed_at"):
        return
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(db, tenant_id, "Marketing: your weekly insights are ready", (row.brief or {}).get("headline", "")[:140],
                       url="/dashboard/marketing/studio?tab=report", tag=f"marketing-insights-{row.id}")
    except Exception as exc:  # noqa: BLE001
        log.warning("marketing_insights_push_failed", tenant_id=tenant_id, error=type(exc).__name__)
    row.delivery = {**(row.delivery or {}), "pushed_at": datetime.now(timezone.utc).isoformat()}


def latest(db: Session, tenant_id: str) -> Optional[AnalystReport]:
    return (db.query(AnalystReport).filter_by(tenant_id=tenant_id, kind=insights.KIND)
            .order_by(AnalystReport.period_start.desc()).first())


def view(r: AnalystReport) -> dict:
    """The report for the screen (money throughout, so the endpoint needs marketing.approve)."""
    return {"id": r.id, "period": {"from": r.period_start.isoformat(), "to": r.period_end.isoformat()},
            "brief": r.brief or {}, "source": r.brief_source, "facts": r.facts or {}, "created_at": r.created_at,
            "prompt_version": r.prompt_version}
