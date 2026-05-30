"""
Ask HAIP — Phase 3: Investigation Path Step Execution

Each investigation path has 3 steps: Analyze → Diagnose → Recommend.
This module defines what each step returns for each path type.

Step execution is:
  - Cumulative: Step 2 includes Step 1 result
  - Lightweight: each step calls 1-2 agents max (data already cached)
  - Opinionated: each step has a focused "question" it answers

Step data shapes:
  Step 1 (Analyze):   KPIs + trend chart + period comparison
  Step 2 (Diagnose):  Drill-down table + top anomaly + root signal
  Step 3 (Recommend): Mini-RCA (Finding + Evidence + 2-3 action items)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Any

from app.adapters.llm import get_llm_adapter
from app.services.ask_haip_agents import (
    run_revenue_agent, run_inquiry_agent, run_guest_agent,
    run_occupancy_agent, run_property_agent, run_channel_agent,
    run_campaign_agent, run_intent_agent, run_objection_agent,
    run_attribution_agent, agents_to_llm_context, AgentOutput,
    _fmt_inr,
)

log = logging.getLogger(__name__)


# ─── Step Result Schema ───────────────────────────────────────────────────────

@dataclass
class StepKPI:
    label: str
    value: Any
    delta_pct: Optional[float] = None
    trend: str = "flat"
    severity: str = "normal"


@dataclass
class StepRow:
    """One row in a diagnostic table."""
    name: str
    primary: str         # main metric
    secondary: str = ""  # supporting metric
    delta: str = ""
    severity: str = "normal"   # critical | warning | good | normal


@dataclass
class StepAction:
    """One recommended action."""
    action: str
    impact: str = ""
    module: str = ""
    href: str = ""
    priority: int = 1   # 1=high, 2=medium, 3=low


@dataclass
class StepResult:
    path_id: str
    step: int
    label: str          # Analyze | Diagnose | Recommend
    headline: str       # one-sentence answer for this step
    kpis: list[StepKPI] = field(default_factory=list)
    rows: list[StepRow] = field(default_factory=list)      # for Diagnose tables
    actions: list[StepAction] = field(default_factory=list)  # for Recommend
    chart: Optional[dict] = None
    finding: str = ""   # key diagnostic sentence
    evidence: list[str] = field(default_factory=list)


# ─── Mini-RCA prompt (for Step 3) ────────────────────────────────────────────

STEP3_PROMPT = """You are a hospitality business analyst. Given analytics data, produce a focused recommendation.

Return strict JSON:
{
  "headline": "One sentence — the most important action to take",
  "finding": "One sentence — what is wrong or what opportunity exists",
  "evidence": ["specific data point 1", "specific data point 2"],
  "actions": [
    {"action": "Specific action", "impact": "Expected outcome", "module": "Module name", "href": "/path", "priority": 1},
    {"action": "Second action", "impact": "Expected outcome", "module": "Module name", "href": "/path", "priority": 2}
  ]
}

Keep actions specific and actionable. Use ₹ for revenue figures. Maximum 3 actions."""


async def _llm_step3(path_id: str, agent_output: dict, context: str) -> dict:
    """Run a mini-RCA for Step 3 of a path."""
    llm = get_llm_adapter()
    user_msg = f"Path: {path_id}\n\nAgent data:\n{context}\n\nProvide focused recommendation."
    try:
        result = await llm.complete(
            system_prompt=STEP3_PROMPT,
            user_message=user_msg,
            max_tokens=512,
        )
        content = result.get("content", "").strip()
        start, end = content.find("{"), content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception as e:
        log.warning("Step 3 LLM failed for %s: %s", path_id, e)
    return {}


# ─── Path Step Definitions ────────────────────────────────────────────────────

async def execute_revenue_step(step: int, raw_data: dict) -> StepResult:
    out = run_revenue_agent(raw_data)

    if step == 1:
        # Analyze: Revenue trend + KPIs
        exec_d = raw_data.get("/analytics/executive") or {}
        rev_mtd  = float(exec_d.get("revenue_mtd") or 0)
        rev_prev = float(exec_d.get("revenue_prev") or 0)
        delta    = round((rev_mtd - rev_prev) / max(rev_prev, 1) * 100, 1) if rev_prev else 0
        fcast_d  = raw_data.get("/analytics/forecasting/revenue") or {}

        kpis = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                for k in out.kpis[:4]]
        chart = {"type": "area", "label": "Revenue Trend",
                 "series": exec_d.get("revenue_chart", [])}

        return StepResult(
            path_id="revenue", step=1, label="Analyze",
            headline=f"Revenue MTD: {_fmt_inr(rev_mtd)} "
                    f"({'+' if delta>=0 else ''}{delta:.1f}% vs prior period)",
            kpis=kpis, chart=chart,
            finding=out.summary,
        )

    elif step == 2:
        # Diagnose: Which property/channel dropped most
        prop_d = raw_data.get("/analytics/properties") or {}
        props  = prop_d.get("properties", [])
        rows = [
            StepRow(
                name=p.get("name","?"),
                primary=_fmt_inr(float(p.get("revenue_mtd", 0) or 0)),
                secondary=f"{p.get('occupancy_pct',0):.1f}% occ",
                delta=f"ADR {_fmt_inr(float(p.get('adr',0) or 0))}",
                severity="warning" if float(p.get("occupancy_pct", 100) or 100) < 50 else "normal",
            )
            for p in sorted(props, key=lambda x: float(x.get("revenue_mtd",0) or 0))
        ]

        finding = (out.top_concern or out.findings[0] if out.findings else
                   "No significant revenue anomalies detected")

        return StepResult(
            path_id="revenue", step=2, label="Diagnose",
            headline="Property-level revenue breakdown — identifying the biggest gap",
            kpis=[], rows=rows, finding=finding,
            evidence=out.findings[:3],
        )

    else:  # step == 3
        ctx = agents_to_llm_context({"revenue": asdict(out)})
        llm_result = await _llm_step3("revenue", asdict(out), ctx)
        actions = [
            StepAction(**a) for a in llm_result.get("actions", [])
        ] if llm_result.get("actions") else [
            StepAction("Review and adjust pricing for low-occupancy properties",
                      "Estimated +10-15% RevPAR uplift",
                      "Revenue Calculator", "/dashboard/revenue-calculator", 1),
            StepAction("Launch win-back campaign to lost leads from last 30 days",
                      "15-20 recoverable leads",
                      "Campaigns", "/dashboard/campaigns/new", 2),
        ]
        return StepResult(
            path_id="revenue", step=3, label="Recommend",
            headline=llm_result.get("headline", "Revenue recovery requires pricing + outreach action"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_inquiry_step(step: int, raw_data: dict) -> StepResult:
    out = run_inquiry_agent(raw_data)
    exec_d = raw_data.get("/analytics/executive") or {}

    if step == 1:
        kpis = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                for k in out.kpis[:5]]
        funnel = exec_d.get("funnel", [])
        chart  = {"type": "funnel", "label": "Inquiry Funnel", "series": funnel}
        return StepResult(
            path_id="inquiry", step=1, label="Analyze",
            headline=out.summary,
            kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        # Diagnose: stage-by-stage leak
        funnel = exec_d.get("funnel", [])
        rows = []
        stages = ["NEW", "RESPONDING", "QUOTED", "SITE_VISIT", "BOOKED"]
        for i, stage in enumerate(stages):
            curr = next((s.get("count", 0) for s in funnel if s.get("stage") == stage), 0)
            prev_stage = stages[i-1] if i > 0 else None
            prev_count = next((s.get("count", 0) for s in funnel if s.get("stage") == prev_stage), curr) if prev_stage else curr
            drop = round((prev_count - curr) / max(prev_count, 1) * 100, 1) if prev_count > curr else 0
            rows.append(StepRow(
                name=stage.replace("_", " ").title(),
                primary=str(curr),
                secondary=f"-{drop:.0f}% drop" if drop > 30 else "",
                severity="critical" if drop > 60 else ("warning" if drop > 40 else "normal"),
            ))

        lost_d = raw_data.get("/analytics/lost-reasons") or {}
        themes = lost_d if isinstance(lost_d, list) else []
        evidence = [f"Lost reason: {t.get('theme','?')} ({t.get('count',0)} times)" for t in themes[:3]]

        return StepResult(
            path_id="inquiry", step=2, label="Diagnose",
            headline="Funnel leak analysis — where are inquiries dropping off?",
            rows=rows, finding=out.top_concern or "Analyse stage drop-offs above",
            evidence=evidence or out.findings[:3],
        )

    else:
        ctx = agents_to_llm_context({"inquiry": asdict(out)})
        llm_result = await _llm_step3("inquiry", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Set SLA alerts for inquiries >2h without response",
                      "Reduce ghosting by 20-30%", "Inbox", "/dashboard/inbox", 1),
            StepAction("Create follow-up flow for quoted but unconverted leads",
                      "5-10% conversion recovery", "Flow Builder", "/dashboard/flows", 2),
        ]
        return StepResult(
            path_id="inquiry", step=3, label="Recommend",
            headline=llm_result.get("headline", "Fix SLA and follow-up automation"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_channel_step(step: int, raw_data: dict) -> StepResult:
    out = run_channel_agent(raw_data)

    if step == 1:
        kpis = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                for k in out.kpis[:5]]
        ch_d    = raw_data.get("/analytics/channels") or {}
        chart   = {"type": "bar", "label": "Channel Volume",
                   "series": ch_d.get("volume_trend", [])}
        return StepResult(
            path_id="channel", step=1, label="Analyze",
            headline=out.summary, kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        att_d     = raw_data.get("/analytics/attribution") or {}
        first_rows = att_d.get("first_touch_breakdown", [])
        rows = [
            StepRow(
                name=r.get("source","?"),
                primary=f"{r.get('conversion_pct',0):.1f}% CVR",
                secondary=_fmt_inr(float(r.get("revenue",0) or 0)),
                delta=f"{r.get('avg_days_to_convert',0):.1f}d avg",
                severity="warning" if float(r.get("conversion_pct",100) or 100) < 10 else "normal",
            )
            for r in first_rows[:8]
        ]
        return StepResult(
            path_id="channel", step=2, label="Diagnose",
            headline="Channel-by-channel conversion and revenue attribution",
            rows=rows, finding=out.top_concern or out.summary,
            evidence=out.findings[:3],
        )

    else:
        ctx = agents_to_llm_context({"channel": asdict(out)})
        llm_result = await _llm_step3("channel", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Increase budget on top-converting channel",
                      "Scale what works", "Campaigns", "/dashboard/campaigns/new", 1),
            StepAction("Review WhatsApp template quality score",
                      "Improve delivery rate", "Integrations", "/dashboard/integrations", 2),
        ]
        return StepResult(
            path_id="channel", step=3, label="Recommend",
            headline=llm_result.get("headline", "Double down on best-converting channel"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_objection_step(step: int, raw_data: dict) -> StepResult:
    out = run_objection_agent(raw_data)
    obj_d = raw_data.get("/analytics/objections") or {}

    if step == 1:
        kpis = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                for k in out.kpis[:4]]
        objections = obj_d.get("objections", [])
        chart = {"type": "bar", "label": "Objections by Revenue Lost", "series": [
            {"name": o.get("label","?"), "value": float(o.get("revenue_lost", 0) or 0)}
            for o in objections[:6]
        ]}
        return StepResult(
            path_id="objection", step=1, label="Analyze",
            headline=out.summary, kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        objections = obj_d.get("objections", [])
        rows = [
            StepRow(
                name=o.get("label","?"),
                primary=f"{o.get('count',0)} inquiries lost",
                secondary=_fmt_inr(float(o.get("revenue_lost",0) or 0)),
                delta=f"{o.get('pct',0):.1f}% of losses",
                severity="critical" if float(o.get("pct", 0) or 0) > 30 else
                         ("warning" if float(o.get("pct",0) or 0) > 15 else "normal"),
            )
            for o in sorted(objections, key=lambda x: float(x.get("revenue_lost",0) or 0), reverse=True)
        ]
        competitors = obj_d.get("competitors", [])
        evidence = [f"Competitor '{c.get('name','?')}' mentioned {c.get('count',0)} times"
                   for c in competitors[:3]] + out.findings[:2]
        return StepResult(
            path_id="objection", step=2, label="Diagnose",
            headline="Objection Pareto — which objection loses the most revenue?",
            rows=rows, finding=out.top_concern or out.summary,
            evidence=evidence[:4],
        )

    else:
        ctx = agents_to_llm_context({"objection": asdict(out)})
        llm_result = await _llm_step3("objection", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Create budget-objection handling script for team",
                      "Reduce budget objections by 20%", "AI Intelligence", "/dashboard/qa", 1),
            StepAction("Offer limited-time discount to recent budget-objection leads",
                      "Recover 5-10 lost bookings", "Campaigns", "/dashboard/campaigns/new", 2),
        ]
        return StepResult(
            path_id="objection", step=3, label="Recommend",
            headline=llm_result.get("headline", "Address price sensitivity with targeted offers"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_guest_step(step: int, raw_data: dict) -> StepResult:
    out = run_guest_agent(raw_data)

    if step == 1:
        kpis = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                for k in out.kpis[:5]]
        cohort_d = raw_data.get("/analytics/forecasting/cohorts") or {}
        cohorts  = cohort_d.get("cohorts", [])
        chart    = {"type": "bar", "label": "Repeat Rate by Cohort", "series": [
            {"name": c.get("cohort","?"), "value": c.get("returned_pct", 0)}
            for c in cohorts
        ]}
        return StepResult(
            path_id="guest", step=1, label="Analyze",
            headline=out.summary, kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        churn_d = raw_data.get("/analytics/forecasting/churn") or {}
        at_risk  = churn_d.get("at_risk_guests", [])
        rows = [
            StepRow(
                name=g.get("name","?"),
                primary=_fmt_inr(float(g.get("lifetime_value",0) or 0)),
                secondary=f"{g.get('total_stays',0)} stays",
                delta=f"{g.get('days_since_contact',0)}d silent",
                severity=g.get("risk_label","normal"),
            )
            for g in at_risk[:10]
        ]
        return StepResult(
            path_id="guest", step=2, label="Diagnose",
            headline="High-value guests at churn risk — sorted by LTV",
            rows=rows, finding=out.top_concern or out.summary,
            evidence=out.findings[:3],
        )

    else:
        ctx = agents_to_llm_context({"guest": asdict(out)})
        llm_result = await _llm_step3("guest", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Send re-engagement campaign to 45d+ silent guests",
                      "Recover 10-20% at-risk revenue", "Campaigns", "/dashboard/campaigns/new", 1),
            StepAction("Assign VIP follow-up call to top 10 at-risk guests",
                      "High-touch recovery for biggest LTV", "Inbox", "/dashboard/inbox", 2),
        ]
        return StepResult(
            path_id="guest", step=3, label="Recommend",
            headline=llm_result.get("headline", "Re-engage high-LTV guests before they churn"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_property_step(step: int, raw_data: dict) -> StepResult:
    out = run_property_agent(raw_data)

    if step == 1:
        kpis = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                for k in out.kpis[:4]]
        prop_d = raw_data.get("/analytics/properties") or {}
        props  = prop_d.get("properties", [])
        chart  = {"type": "bar", "label": "RevPAR by Property", "series": [
            {"name": p.get("name","?"), "value": float(p.get("revpar",0) or 0)}
            for p in sorted(props, key=lambda x: float(x.get("revpar",0) or 0), reverse=True)
        ]}
        return StepResult(
            path_id="property", step=1, label="Analyze",
            headline=out.summary, kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        prop_d = raw_data.get("/analytics/properties") or {}
        props  = prop_d.get("properties", [])
        rows = [
            StepRow(
                name=p.get("name","?"),
                primary=f"RevPAR {_fmt_inr(float(p.get('revpar',0) or 0))}",
                secondary=f"{p.get('occupancy_pct',0):.1f}% occ",
                delta=f"ADR {_fmt_inr(float(p.get('adr',0) or 0))}",
                severity="warning" if float(p.get("occupancy_pct",100) or 100) < 50 else "normal",
            )
            for p in sorted(props, key=lambda x: float(x.get("revpar",0) or 0))
        ]
        return StepResult(
            path_id="property", step=2, label="Diagnose",
            headline="Property RevPAR ladder — lowest to highest performer",
            rows=rows, finding=out.top_concern or out.summary,
            evidence=out.findings[:3],
        )

    else:
        ctx = agents_to_llm_context({"property": asdict(out)})
        llm_result = await _llm_step3("property", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Apply dynamic pricing suggestion to lowest-RevPAR property",
                      "+8-15% RevPAR uplift", "Revenue Calculator", "/dashboard/revenue-calculator", 1),
            StepAction("Review blocked dates on underperforming property",
                      "Release unnecessary blocks", "Calendar", "/dashboard/calendar", 2),
        ]
        return StepResult(
            path_id="property", step=3, label="Recommend",
            headline=llm_result.get("headline", "Prioritise lowest-RevPAR property for immediate action"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_intent_step(step: int, raw_data: dict) -> StepResult:
    out = run_intent_agent(raw_data)
    int_d = raw_data.get("/analytics/intent") or {}

    if step == 1:
        kpis  = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                 for k in out.kpis[:4]]
        dist  = int_d.get("intent_distribution", [])
        chart = {"type": "pie", "label": "Intent Distribution", "series": [
            {"name": b.get("intent","?").replace("_"," ").title(), "value": b.get("count",0)}
            for b in dist
        ]}
        return StepResult(
            path_id="intent", step=1, label="Analyze",
            headline=out.summary, kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        dist = int_d.get("intent_distribution", [])
        rows = [
            StepRow(
                name=b.get("intent","?").replace("_"," ").title(),
                primary=f"{b.get('conversion_pct',0):.1f}% CVR",
                secondary=_fmt_inr(float(b.get("avg_booking_value",0) or 0)),
                delta=_fmt_inr(float(b.get("revenue",0) or 0)),
                severity="good" if float(b.get("conversion_pct",0) or 0) > 35 else
                         ("warning" if float(b.get("conversion_pct",0) or 0) < 15 else "normal"),
            )
            for b in sorted(dist, key=lambda x: float(x.get("conversion_pct",0) or 0), reverse=True)
        ]
        return StepResult(
            path_id="intent", step=2, label="Diagnose",
            headline="Intent-by-intent conversion and revenue — where to focus",
            rows=rows, finding=out.top_positive or out.summary,
            evidence=out.findings[:3],
        )

    else:
        ctx = agents_to_llm_context({"intent": asdict(out)})
        llm_result = await _llm_step3("intent", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Create campaign targeting top-converting intent segment",
                      "+15% inquiry volume from best segment", "Campaigns", "/dashboard/campaigns/new", 1),
            StepAction("Update property FAQs to address top intent needs",
                      "Improve lead quality", "Properties", "/dashboard/portfolio", 2),
        ]
        return StepResult(
            path_id="intent", step=3, label="Recommend",
            headline=llm_result.get("headline", "Double down on highest-converting intent segment"),
            finding=llm_result.get("finding", out.top_positive or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


async def execute_campaign_step(step: int, raw_data: dict) -> StepResult:
    out = run_campaign_agent(raw_data)
    camp_d = raw_data.get("/analytics/campaigns") or {}

    if step == 1:
        kpis  = [StepKPI(k.label, k.value, k.delta_pct, k.trend, k.severity or "normal")
                 for k in out.kpis[:4]]
        trend = camp_d.get("subscriber_trend", [])
        chart = {"type": "line", "label": "Subscriber Growth", "series": trend}
        return StepResult(
            path_id="campaign", step=1, label="Analyze",
            headline=out.summary, kpis=kpis, chart=chart, finding=out.summary,
        )

    elif step == 2:
        templates = camp_d.get("template_performance", [])
        rows = [
            StepRow(
                name=t.get("name","?"),
                primary=f"{t.get('delivery_rate',0):.1f}% delivery",
                secondary=f"{t.get('read_rate',0):.1f}% read",
                severity="warning" if float(t.get("delivery_rate",100) or 100) < 85 else "normal",
            )
            for t in sorted(templates, key=lambda x: float(x.get("read_rate",0) or 0), reverse=True)
        ]
        return StepResult(
            path_id="campaign", step=2, label="Diagnose",
            headline="Template performance ranking — delivery and read rates",
            rows=rows, finding=out.top_concern or out.summary,
            evidence=out.findings[:3],
        )

    else:
        ctx = agents_to_llm_context({"campaign": asdict(out)})
        llm_result = await _llm_step3("campaign", asdict(out), ctx)
        actions = [StepAction(**a) for a in llm_result.get("actions", [])] if llm_result.get("actions") else [
            StepAction("Pause low-delivery templates and submit for re-approval",
                      "Restore delivery rate to 95%+", "Integrations", "/dashboard/integrations", 1),
            StepAction("Clone best-performing template for next campaign",
                      "+20% read rate", "Campaigns", "/dashboard/campaigns/new", 2),
        ]
        return StepResult(
            path_id="campaign", step=3, label="Recommend",
            headline=llm_result.get("headline", "Fix template delivery and replicate what works"),
            finding=llm_result.get("finding", out.top_concern or ""),
            evidence=llm_result.get("evidence", out.findings[:3]),
            actions=actions,
        )


# ─── Step Dispatcher ──────────────────────────────────────────────────────────

STEP_HANDLERS = {
    "revenue":   execute_revenue_step,
    "inquiry":   execute_inquiry_step,
    "channel":   execute_channel_step,
    "objection": execute_objection_step,
    "guest":     execute_guest_step,
    "property":  execute_property_step,
    "intent":    execute_intent_step,
    "campaign":  execute_campaign_step,
}


async def execute_step(
    path_id: str,
    step: int,
    raw_data: dict,
) -> dict:
    """
    Execute a single step for a path and return StepResult as dict.
    Cumulative: step N returns results for steps 1..N.
    """
    handler = STEP_HANDLERS.get(path_id)
    if not handler:
        return {"error": f"Unknown path: {path_id}", "path_id": path_id, "step": step}

    # Cumulative: execute steps 1..N and collect all
    cumulative_steps = []
    for s in range(1, step + 1):
        try:
            result = await handler(s, raw_data)
            cumulative_steps.append(asdict(result))
        except Exception as e:
            log.error("Step execution failed: path=%s step=%d error=%s", path_id, s, e)
            cumulative_steps.append({"path_id": path_id, "step": s, "error": str(e)})

    return {
        "path_id": path_id,
        "steps_executed": step,
        "cumulative": cumulative_steps,
    }


async def execute_all_paths(raw_data: dict, domains: list[str]) -> dict[str, dict]:
    """Run all available paths to Step 3 in parallel — 'Run All' mode."""
    import asyncio
    paths_to_run = [d for d in domains if d in STEP_HANDLERS]
    tasks = {path_id: execute_step(path_id, 3, raw_data) for path_id in paths_to_run}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {
        path_id: (r if not isinstance(r, Exception) else {"error": str(r)})
        for path_id, r in zip(tasks.keys(), results)
    }
