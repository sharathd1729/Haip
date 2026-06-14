"""
Ask HAIP — Phase 5: Report Generation Engine

7 report types:
  1. executive  — 6 KPIs, top finding, top recommendation
  2. weekly     — 5 KPI deltas, top win, top concern, actions
  3. monthly    — Full month analysis across 10 domains
  4. property   — Per-property: occupancy, revenue, ADR, RevPAR
  5. guest      — Top guests by LTV, churn risk, last contact
  6. revenue    — MTD vs forecast, channel mix, property breakdown
  7. inquiry    — Funnel, lost reasons, objections, agent leaderboard

Each report:
  1. Runs relevant agent processors (reuses Phase 2 agents)
  2. LLM synthesises a 200-300 word narrative (Haiku — cost efficient)
  3. Renders an HTML report with inline CSS (no external deps)
  4. Saves to ask_haip_reports table
  5. Optionally emails to owner
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional

from sqlalchemy.orm import Session

from app.adapters.llm import get_llm
from app.models.ask_haip import AskHaipReport
from app.models.base import gen_uuid
from app.services.ask_haip_agents import (
    run_revenue_agent, run_inquiry_agent, run_guest_agent,
    run_occupancy_agent, run_property_agent, run_channel_agent,
    run_campaign_agent, run_intent_agent, run_objection_agent,
    agents_to_llm_context, _fmt_inr,
)
from app.services.ask_haip_rca import build_correlations, calculate_confidence

log = logging.getLogger(__name__)

REPORT_TYPES = ["executive", "weekly", "monthly", "property", "guest", "revenue", "inquiry"]


# ─── Narrative Synthesis ──────────────────────────────────────────────────────

NARRATIVE_PROMPT = """You are a hospitality business analyst writing a concise report summary.
Given analytics data, write a 3-paragraph narrative (150-200 words total):
- Paragraph 1: Overall performance headline (what happened)
- Paragraph 2: Key concern or opportunity (why it matters)
- Paragraph 3: Top 2 recommended actions

Rules: Use specific numbers. Indian Rupee format (₹4.2L). Professional but readable tone.
Return plain text only — no markdown, no headings."""


async def _generate_narrative(context: str, report_type: str, period: str) -> str:
    """Generate a short narrative using Claude Haiku (cost-efficient)."""
    llm = get_llm("report_gen")
    try:
        result = await llm.complete(
            system_prompt=NARRATIVE_PROMPT,
            user_message=f"Report type: {report_type}\nPeriod: {period}\n\nData:\n{context[:3000]}",
            max_tokens=400,
        )
        return result.get("content", "").strip()
    except Exception as e:
        log.warning("Narrative generation failed: %s", e)
        return "Analytics data processed. See metrics below for full detail."


# ─── HTML Template Engine ─────────────────────────────────────────────────────

REPORT_CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background:#f8fafc; color:#1e293b; margin:0; padding:24px; }
  .wrapper { max-width:760px; margin:0 auto; }
  .header  { background:linear-gradient(135deg,#0f766e,#0d9488); color:white;
             border-radius:16px; padding:28px 32px; margin-bottom:24px; }
  .header h1 { margin:0 0 4px; font-size:22px; font-weight:700; }
  .header p  { margin:0; opacity:0.8; font-size:13px; }
  .kpi-grid  { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
               gap:12px; margin-bottom:24px; }
  .kpi-card  { background:white; border:1px solid #e2e8f0; border-radius:12px;
               padding:16px; }
  .kpi-value { font-size:22px; font-weight:700; color:#0f766e; margin:0 0 4px; }
  .kpi-delta.up   { color:#16a34a; font-size:11px; }
  .kpi-delta.down { color:#dc2626; font-size:11px; }
  .kpi-label { font-size:11px; color:#64748b; margin:0; }
  .section   { background:white; border:1px solid #e2e8f0; border-radius:12px;
               padding:20px; margin-bottom:16px; }
  .section h2{ font-size:14px; font-weight:600; margin:0 0 12px; color:#334155; }
  .narrative { font-size:13px; line-height:1.7; color:#475569; }
  .findings  { list-style:none; padding:0; margin:0; }
  .finding   { border-left:3px solid #0d9488; padding:10px 12px; margin-bottom:10px;
               background:#f0fdf4; border-radius:0 8px 8px 0; font-size:13px; }
  .finding.critical { border-color:#ef4444; background:#fef2f2; }
  .finding.warning  { border-color:#f59e0b; background:#fffbeb; }
  .finding strong { display:block; margin-bottom:4px; font-size:13px; }
  .table     { width:100%; border-collapse:collapse; font-size:12px; }
  .table th  { text-align:left; padding:8px 12px; background:#f1f5f9;
               font-weight:600; color:#475569; font-size:11px; text-transform:uppercase; }
  .table td  { padding:8px 12px; border-bottom:1px solid #f1f5f9; }
  .badge     { display:inline-block; padding:2px 8px; border-radius:9999px; font-size:10px; font-weight:600; }
  .badge-red   { background:#fee2e2; color:#b91c1c; }
  .badge-amber { background:#fef3c7; color:#b45309; }
  .badge-green { background:#dcfce7; color:#15803d; }
  .badge-gray  { background:#f1f5f9; color:#475569; }
  .action    { background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px;
               padding:10px 14px; margin-bottom:8px; font-size:12px; }
  .action strong { color:#0f766e; }
  .footer    { text-align:center; font-size:11px; color:#94a3b8; margin-top:24px; }
  .severity-critical { color:#dc2626; }
  .severity-warning  { color:#d97706; }
  .severity-good     { color:#16a34a; }
"""


def _kpi_card(label: str, value: str, delta_pct: Optional[float] = None, severity: str = "normal") -> str:
    delta_html = ""
    if delta_pct is not None:
        cls = "up" if delta_pct >= 0 else "down"
        arrow = "▲" if delta_pct >= 0 else "▼"
        delta_html = f'<p class="kpi-delta {cls}">{arrow} {abs(delta_pct):.1f}% vs prior</p>'
    sev_cls = f'severity-{severity}' if severity in ("critical","warning","good") else ""
    return f"""
    <div class="kpi-card">
      <p class="kpi-value {sev_cls}">{value}</p>
      {delta_html}
      <p class="kpi-label">{label}</p>
    </div>"""


def _finding_item(title: str, body: str = "", severity: str = "normal") -> str:
    cls = "critical" if severity in ("critical","high") else ("warning" if severity == "warning" else "")
    return f"""<li class="finding {cls}"><strong>{title}</strong>{body}</li>"""


def _table_row(*cells: str) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _action_item(action: str, impact: str = "", module: str = "") -> str:
    mod_html = f' <span class="badge badge-green">{module}</span>' if module else ""
    return f'<div class="action"><strong>{action}</strong>{mod_html}<br><span style="color:#64748b">{impact}</span></div>'


def _wrap_report(title: str, subtitle: str, period: str, body: str) -> str:
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>HAIP Report — {title}</title>
<style>{REPORT_CSS}</style></head><body>
<div class="wrapper">
  <div class="header">
    <h1>✦ {title}</h1>
    <p>{subtitle} · {period} · Generated {now}</p>
  </div>
  {body}
  <p class="footer">Generated by HAIP Intelligence · Ask HAIP · Confidential</p>
</div></body></html>"""


# ─── Report Builders ──────────────────────────────────────────────────────────

async def build_executive_report(raw_data: dict, range_days: int) -> tuple[str, str]:
    """Returns (title, html)"""
    exec_d = raw_data.get("/analytics/executive") or {}
    rev_out = run_revenue_agent(raw_data)
    occ_out = run_occupancy_agent(raw_data)
    inq_out = run_inquiry_agent(raw_data)

    rev_mtd  = float(exec_d.get("revenue_mtd") or 0)
    rev_prev = float(exec_d.get("revenue_prev") or 0)
    occ_pct  = float(exec_d.get("occupancy_pct") or 0)
    active   = int(exec_d.get("active_inquiries") or 0)
    qa_score = float(exec_d.get("qa_avg_score") or 0)
    sla_pct  = float(exec_d.get("sla_compliance_pct") or 0)
    ai_rate  = float(exec_d.get("ai_draft_rate_pct") or 0)

    rev_delta = round((rev_mtd - rev_prev) / max(rev_prev, 1) * 100, 1) if rev_prev else None

    period = f"Last {range_days} days"
    ctx = agents_to_llm_context({"revenue": vars(rev_out) if hasattr(rev_out,"__dict__") else {},
                                  "occupancy": {}, "inquiry": {}})
    narrative = await _generate_narrative(ctx, "executive", period)

    # Signals
    signals = build_correlations(["revenue","occupancy","inquiry","channel"], raw_data, {})
    critical = [s for s in signals if s["severity"] == "critical"][:3]

    kpis = "".join([
        _kpi_card("Revenue MTD", _fmt_inr(rev_mtd), rev_delta,
                  "critical" if (rev_delta or 0) < -15 else ("good" if (rev_delta or 0) > 10 else "normal")),
        _kpi_card("Occupancy %", f"{occ_pct}%",
                  severity="critical" if occ_pct < 40 else ("warning" if occ_pct < 60 else "good")),
        _kpi_card("Active Inquiries", str(active)),
        _kpi_card("Avg QA Score", f"{qa_score:.1f}/100"),
        _kpi_card("SLA Compliance", f"{sla_pct}%",
                  severity="critical" if sla_pct < 70 else ("warning" if sla_pct < 85 else "good")),
        _kpi_card("AI Draft Rate", f"{ai_rate}%"),
    ])

    findings_html = "<ul class='findings'>" + "".join(
        _finding_item(s["message"], severity=s["severity"]) for s in critical
    ) + "</ul>" if critical else "<p style='color:#64748b;font-size:13px'>No critical signals this period.</p>"

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>Executive Summary</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section">
      <h2>Critical Signals</h2>
      {findings_html}
    </div>"""

    title = f"Executive Report — {period}"
    return title, _wrap_report("Executive Report", "Portfolio Performance", period, body)


async def build_weekly_report(raw_data: dict) -> tuple[str, str]:
    """Weekly digest — deltas, top win, top concern, 3 actions."""
    exec_d = raw_data.get("/analytics/executive") or {}
    rev_out = run_revenue_agent(raw_data)
    occ_out = run_occupancy_agent(raw_data)
    ch_out  = run_channel_agent(raw_data)

    rev_mtd  = float(exec_d.get("revenue_mtd") or 0)
    rev_prev = float(exec_d.get("revenue_prev") or 0)
    occ_pct  = float(exec_d.get("occupancy_pct") or 0)
    rev_delta = round((rev_mtd - rev_prev) / max(rev_prev, 1) * 100, 1) if rev_prev else None

    period = f"Week ending {datetime.now().strftime('%d %b %Y')}"
    ctx    = agents_to_llm_context({
        "revenue": {}, "occupancy": {}, "channel": {}
    })
    narrative = await _generate_narrative(ctx, "weekly", period)

    signals = build_correlations(["revenue","occupancy","inquiry"], raw_data, {})
    top_concern  = next((s["message"] for s in signals if s["severity"] == "critical"), None)
    top_positive = next((s["message"] for s in signals if s["severity"] == "positive"), None)

    kpis = "".join([
        _kpi_card("Revenue MTD", _fmt_inr(rev_mtd), rev_delta),
        _kpi_card("Occupancy", f"{occ_pct}%"),
        _kpi_card("Active Inquiries", str(int(exec_d.get("active_inquiries") or 0))),
        _kpi_card("SLA Compliance", f"{exec_d.get('sla_compliance_pct',0):.1f}%"),
        _kpi_card("AI Draft Rate", f"{exec_d.get('ai_draft_rate_pct',0):.1f}%"),
    ])

    concern_html = _finding_item(top_concern, severity="critical") if top_concern else ""
    win_html     = _finding_item(top_positive, severity="normal") if top_positive else ""

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>This Week</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section">
      <h2>Top Concern</h2>
      <ul class="findings">{concern_html or "<li class='finding'>No critical issues this week.</li>"}</ul>
    </div>
    <div class="section">
      <h2>Top Win</h2>
      <ul class="findings">{win_html or "<li class='finding'>Keep monitoring for positive signals.</li>"}</ul>
    </div>"""

    return f"Weekly Digest — {period}", _wrap_report("Weekly Digest", "7-Day Performance Summary", period, body)


async def build_revenue_report(raw_data: dict) -> tuple[str, str]:
    """Revenue deep-dive: MTD, forecast, property breakdown, channel attribution."""
    exec_d  = raw_data.get("/analytics/executive") or {}
    fcast_d = raw_data.get("/analytics/forecasting/revenue") or {}
    prop_d  = raw_data.get("/analytics/properties") or {}
    att_d   = raw_data.get("/analytics/attribution") or {}

    rev_mtd   = float(exec_d.get("revenue_mtd") or 0)
    rev_prev  = float(exec_d.get("revenue_prev") or 0)
    rev_delta = round((rev_mtd - rev_prev) / max(rev_prev, 1) * 100, 1) if rev_prev else None
    forecast  = float(fcast_d.get("full_month_forecast") or 0)
    ytd       = float(fcast_d.get("ytd_actual") or 0)

    props = sorted(
        prop_d.get("properties", []),
        key=lambda p: float(p.get("revenue_mtd", 0) or 0), reverse=True
    )

    period = f"Month to {datetime.now().strftime('%d %b %Y')}"
    ctx    = agents_to_llm_context({"revenue": {}})
    narrative = await _generate_narrative(ctx, "revenue", period)

    kpis = "".join([
        _kpi_card("Revenue MTD", _fmt_inr(rev_mtd), rev_delta),
        _kpi_card("Full Month Forecast", _fmt_inr(forecast)),
        _kpi_card("YTD Actual", _fmt_inr(ytd)),
        _kpi_card("Top Source", att_d.get("top_first_touch") or "—"),
    ])

    rows = "".join(_table_row(
        p.get("name","?"),
        _fmt_inr(float(p.get("revenue_mtd",0) or 0)),
        _fmt_inr(float(p.get("adr",0) or 0)),
        f"{p.get('occupancy_pct',0):.1f}%",
        f"{p.get('direct_pct',0):.0f}% direct",
    ) for p in props[:10])

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>Revenue Analysis</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section">
      <h2>Property Revenue Breakdown</h2>
      <table class="table">
        <thead><tr>
          <th>Property</th><th>Revenue MTD</th><th>ADR</th><th>Occupancy</th><th>Channel Mix</th>
        </tr></thead>
        <tbody>{rows or "<tr><td colspan='5' style='color:#94a3b8'>No property data</td></tr>"}</tbody>
      </table>
    </div>"""

    return f"Revenue Report — {period}", _wrap_report("Revenue Report", "Income & Forecast Analysis", period, body)


async def build_inquiry_report(raw_data: dict) -> tuple[str, str]:
    """Inquiry funnel, lost reasons, agent leaderboard."""
    exec_d  = raw_data.get("/analytics/executive") or {}
    daily_d = raw_data.get("/analytics/owner-daily") or {}
    obj_d   = raw_data.get("/analytics/objections") or {}
    ops_d   = raw_data.get("/analytics/operations") or {}

    funnel  = exec_d.get("funnel", [])
    agents  = ops_d.get("agents", []) if ops_d else []
    themes  = daily_d.get("lost_reason_themes", [])

    period = f"Last 30 days"
    ctx    = agents_to_llm_context({"inquiry": {}})
    narrative = await _generate_narrative(ctx, "inquiry", period)

    active   = int(exec_d.get("active_inquiries") or 0)
    new_inq  = next((s.get("count",0) for s in funnel if s.get("stage") == "NEW"), 0)
    booked   = next((s.get("count",0) for s in funnel if s.get("stage") == "BOOKED"), 0)
    cvr      = round(booked / max(new_inq, 1) * 100, 1)

    kpis = "".join([
        _kpi_card("Active Inquiries", str(active)),
        _kpi_card("New Inquiries", str(new_inq)),
        _kpi_card("Bookings", str(booked)),
        _kpi_card("Conversion Rate", f"{cvr}%",
                  severity="critical" if cvr < 10 else ("warning" if cvr < 20 else "good")),
        _kpi_card("SLA Compliance", f"{exec_d.get('sla_compliance_pct',0):.1f}%"),
    ])

    funnel_rows = "".join(_table_row(
        s.get("stage","?").replace("_"," ").title(), str(s.get("count",0))
    ) for s in funnel)

    theme_rows = "".join(_table_row(
        t.get("theme","?"), str(t.get("count",0))
    ) for t in (themes or [])[:8])

    agent_rows = "".join(_table_row(
        a.get("name","?"), str(a.get("calls_handled",0)),
        f"{a.get('avg_qa_score',0):.1f}"
    ) for a in sorted(agents, key=lambda x: x.get("avg_qa_score",0), reverse=True)[:8])

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>Inquiry Analysis</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div>
        <h2>Funnel Stages</h2>
        <table class="table"><thead><tr><th>Stage</th><th>Count</th></tr></thead>
        <tbody>{funnel_rows}</tbody></table>
      </div>
      <div>
        <h2>Lost Reasons</h2>
        <table class="table"><thead><tr><th>Theme</th><th>Count</th></tr></thead>
        <tbody>{theme_rows or "<tr><td colspan='2' style='color:#94a3b8'>No data</td></tr>"}</tbody></table>
      </div>
    </div>
    <div class="section">
      <h2>Agent Leaderboard</h2>
      <table class="table"><thead><tr><th>Agent</th><th>Calls</th><th>QA Score</th></tr></thead>
      <tbody>{agent_rows or "<tr><td colspan='3' style='color:#94a3b8'>No agent data</td></tr>"}</tbody></table>
    </div>"""

    return f"Inquiry Report — {period}", _wrap_report("Inquiry Report", "Lead Funnel & Team Performance", period, body)


async def build_property_report(raw_data: dict) -> tuple[str, str]:
    """Per-property: occupancy, revenue, ADR, RevPAR, pricing."""
    prop_d  = raw_data.get("/analytics/properties") or {}
    fcast_d = raw_data.get("/analytics/forecasting/occupancy") or {}
    price_d = raw_data.get("/analytics/forecasting/pricing") or {}
    props   = prop_d.get("properties", [])

    period = f"Month to {datetime.now().strftime('%d %b %Y')}"
    ctx    = agents_to_llm_context({"property": {}})
    narrative = await _generate_narrative(ctx, "property", period)

    portfolio_occ = float(prop_d.get("portfolio_occupancy") or 0)
    portfolio_rev = float(prop_d.get("portfolio_revenue_mtd") or 0)
    portfolio_adr = float(prop_d.get("portfolio_adr") or 0)
    suggestions   = price_d.get("suggestions", [])

    kpis = "".join([
        _kpi_card("Portfolio Occupancy", f"{portfolio_occ}%",
                  severity="critical" if portfolio_occ < 40 else "normal"),
        _kpi_card("Portfolio Revenue", _fmt_inr(portfolio_rev)),
        _kpi_card("Portfolio ADR", _fmt_inr(portfolio_adr)),
        _kpi_card("Properties", str(len(props))),
    ])

    prop_rows = "".join(_table_row(
        p.get("name","?"),
        f"{p.get('occupancy_pct',0):.1f}%",
        _fmt_inr(float(p.get("revenue_mtd",0) or 0)),
        _fmt_inr(float(p.get("adr",0) or 0)),
        _fmt_inr(float(p.get("revpar",0) or 0)),
        f"{p.get('direct_pct',0):.0f}% / {p.get('ota_pct',0):.0f}%",
    ) for p in sorted(props, key=lambda x: float(x.get("revpar",0) or 0), reverse=True))

    pricing_rows = "".join(_table_row(
        s.get("property_name","?"),
        _fmt_inr(float(s.get("current_price",0) or 0)),
        _fmt_inr(float(s.get("suggested_price",0) or 0)),
        f"{'+' if s.get('delta_pct',0)>0 else ''}{s.get('delta_pct',0):.1f}%",
        s.get("confidence",""),
    ) for s in suggestions[:8])

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>Portfolio Analysis</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section">
      <h2>Property Performance Matrix</h2>
      <table class="table"><thead><tr>
        <th>Property</th><th>Occupancy</th><th>Revenue</th>
        <th>ADR</th><th>RevPAR</th><th>Direct/OTA</th>
      </tr></thead>
      <tbody>{prop_rows or "<tr><td colspan='6' style='color:#94a3b8'>No data</td></tr>"}</tbody></table>
    </div>
    <div class="section">
      <h2>Dynamic Pricing Suggestions</h2>
      <table class="table"><thead><tr>
        <th>Property</th><th>Current</th><th>Suggested</th><th>Change</th><th>Confidence</th>
      </tr></thead>
      <tbody>{pricing_rows or "<tr><td colspan='5' style='color:#94a3b8'>No pricing data</td></tr>"}</tbody></table>
    </div>"""

    return f"Property Report — {period}", _wrap_report("Property Report", "Portfolio Performance", period, body)


async def build_guest_report(raw_data: dict) -> tuple[str, str]:
    """Top guests, churn risk, LTV, cohorts."""
    guest_d  = raw_data.get("/analytics/guests") or {}
    churn_d  = raw_data.get("/analytics/forecasting/churn") or {}
    cohort_d = raw_data.get("/analytics/forecasting/cohorts") or {}

    period = f"As of {datetime.now().strftime('%d %b %Y')}"
    ctx    = agents_to_llm_context({"guest": {}})
    narrative = await _generate_narrative(ctx, "guest", period)

    total       = int(guest_d.get("total_guests") or 0)
    repeat_pct  = float(guest_d.get("repeat_pct") or 0)
    avg_ltv     = float(guest_d.get("avg_ltv") or 0)
    high_risk   = int(churn_d.get("high_risk_count") or 0)
    rev_at_risk = float(churn_d.get("revenue_at_risk") or 0)

    kpis = "".join([
        _kpi_card("Total Guests", str(total)),
        _kpi_card("Repeat Rate", f"{repeat_pct}%",
                  severity="warning" if repeat_pct < 20 else ("good" if repeat_pct > 40 else "normal")),
        _kpi_card("Avg LTV", _fmt_inr(avg_ltv)),
        _kpi_card("High Churn Risk", str(high_risk),
                  severity="critical" if high_risk > 10 else ("warning" if high_risk > 5 else "normal")),
        _kpi_card("Revenue at Risk", _fmt_inr(rev_at_risk)),
    ])

    at_risk_guests = churn_d.get("at_risk_guests", [])
    risk_rows = "".join(_table_row(
        g.get("name","?"),
        g.get("phone",""),
        str(g.get("total_stays",0)),
        _fmt_inr(float(g.get("lifetime_value",0) or 0)),
        f"{g.get('days_since_contact',0)}d",
        f'<span class="badge badge-{"red" if g.get("risk_label")=="high" else "amber" if g.get("risk_label")=="medium" else "gray"}">'
        f'{g.get("risk_label","?")}</span>',
    ) for g in at_risk_guests[:20])

    cohorts = cohort_d.get("cohorts", [])
    cohort_rows = "".join(_table_row(
        c.get("cohort","?"), str(c.get("guests",0)),
        f"{c.get('returned_pct',0):.1f}%", _fmt_inr(float(c.get("avg_ltv",0) or 0)),
        f"{c.get('vip_pct',0):.1f}%",
    ) for c in cohorts)

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>Guest Intelligence</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section">
      <h2>Churn Risk — At-Risk Guests</h2>
      <table class="table"><thead><tr>
        <th>Name</th><th>Phone</th><th>Stays</th><th>LTV</th><th>Days Silent</th><th>Risk</th>
      </tr></thead>
      <tbody>{risk_rows or "<tr><td colspan='6' style='color:#94a3b8'>No at-risk guests</td></tr>"}</tbody></table>
    </div>
    <div class="section">
      <h2>Acquisition Cohort Retention</h2>
      <table class="table"><thead><tr>
        <th>Cohort</th><th>Guests</th><th>Returned %</th><th>Avg LTV</th><th>VIP %</th>
      </tr></thead>
      <tbody>{cohort_rows or "<tr><td colspan='5' style='color:#94a3b8'>No cohort data</td></tr>"}</tbody></table>
    </div>"""

    return f"Guest Report — {period}", _wrap_report("Guest Report", "Guest Base Analysis", period, body)


async def build_monthly_report(raw_data: dict) -> tuple[str, str]:
    """Full month analysis — all 10 domains."""
    now    = datetime.now()
    period = now.strftime("%B %Y")

    # Run all agents
    rev_out  = run_revenue_agent(raw_data)
    occ_out  = run_occupancy_agent(raw_data)
    inq_out  = run_inquiry_agent(raw_data)
    guest_out= run_guest_agent(raw_data)
    ch_out   = run_channel_agent(raw_data)
    obj_out  = run_objection_agent(raw_data)
    int_out  = run_intent_agent(raw_data)

    ctx = agents_to_llm_context({
        "revenue": {}, "occupancy": {}, "inquiry": {},
        "guest": {}, "channel": {}, "objection": {}, "intent": {},
    })
    narrative = await _generate_narrative(ctx, "monthly", period)

    exec_d   = raw_data.get("/analytics/executive") or {}
    rev_mtd  = float(exec_d.get("revenue_mtd") or 0)
    rev_prev = float(exec_d.get("revenue_prev") or 0)
    rev_delta = round((rev_mtd - rev_prev) / max(rev_prev,1) * 100, 1) if rev_prev else None

    kpis = "".join([
        _kpi_card("Revenue MTD", _fmt_inr(rev_mtd), rev_delta),
        _kpi_card("Occupancy", f"{exec_d.get('occupancy_pct',0):.1f}%"),
        _kpi_card("Active Inquiries", str(exec_d.get("active_inquiries",0))),
        _kpi_card("QA Score", f"{exec_d.get('qa_avg_score',0):.1f}"),
        _kpi_card("SLA Compliance", f"{exec_d.get('sla_compliance_pct',0):.1f}%"),
        _kpi_card("AI Draft Rate", f"{exec_d.get('ai_draft_rate_pct',0):.1f}%"),
    ])

    # Cross-agent signals
    signals   = build_correlations(list(range(10)), raw_data, {})
    finding_html = "<ul class='findings'>" + "".join(
        _finding_item(s["message"], severity=s["severity"])
        for s in signals[:6]
    ) + "</ul>"

    body = f"""
    <div class="kpi-grid">{kpis}</div>
    <div class="section">
      <h2>Monthly Summary — {period}</h2>
      <p class="narrative">{narrative}</p>
    </div>
    <div class="section">
      <h2>Key Signals This Month</h2>
      {finding_html}
    </div>
    <div class="section" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div>
        <h2>Top Agent Summaries</h2>
        {''.join(f'<p style="font-size:12px;margin:4px 0"><strong>{a}:</strong> {s}</p>'
          for a, s in [
            ("Revenue", rev_out.summary[:80] + "…" if len(rev_out.summary)>80 else rev_out.summary),
            ("Occupancy", occ_out.summary[:80] + "…"),
            ("Inquiry",  inq_out.summary[:80] + "…"),
            ("Channel",  ch_out.summary[:80] + "…"),
          ]
        )}
      </div>
      <div>
        <h2>Intelligence Highlights</h2>
        {''.join(f'<p style="font-size:12px;margin:4px 0"><strong>{a}:</strong> {s}</p>'
          for a, s in [
            ("Guests",    guest_out.summary[:80] + "…"),
            ("Objections",obj_out.summary[:80] + "…"),
            ("Intent",    int_out.summary[:80] + "…"),
          ]
        )}
      </div>
    </div>"""

    return f"Monthly Report — {period}", _wrap_report("Monthly Report", "Full Portfolio Analysis", period, body)


# ─── Report Dispatcher ────────────────────────────────────────────────────────

REPORT_BUILDERS = {
    "executive": build_executive_report,
    "weekly":    build_weekly_report,
    "monthly":   build_monthly_report,
    "property":  build_property_report,
    "guest":     build_guest_report,
    "revenue":   build_revenue_report,
    "inquiry":   build_inquiry_report,
}


async def generate_report(
    report_type: str,
    raw_data: dict,
    range_days: int = 30,
) -> dict:
    """
    Generate a report and return {title, html, report_type}.
    """
    builder = REPORT_BUILDERS.get(report_type)
    if not builder:
        raise ValueError(f"Unknown report type: {report_type}. Valid: {list(REPORT_BUILDERS)}")

    # Weekly/monthly/guest don't take range_days
    if report_type in ("weekly", "monthly", "property", "guest"):
        title, html = await builder(raw_data)
    else:
        title, html = await builder(raw_data, range_days)

    return {"title": title, "html": html, "report_type": report_type}


def save_report(
    db: Session,
    tenant_id: str,
    report_type: str,
    title: str,
    html: str,
    range_days: int = 30,
) -> AskHaipReport:
    """Persist report to ask_haip_reports table."""
    now = datetime.now(timezone.utc)
    first_of_month = now.replace(day=1).date().isoformat()
    report = AskHaipReport(
        id=gen_uuid(),
        tenant_id=tenant_id,
        report_type=report_type,
        period_start=first_of_month,
        period_end=now.date().isoformat(),
        title=title,
        html_content=html,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


async def send_report_email(
    *,
    to_email: str,
    to_name: str,
    report_type: str,
    title: str,
    html: str,
) -> bool:
    """Email the report HTML via Resend."""
    from app.services.email_service import _send
    subject = f"HAIP {report_type.title()} Report — {title}"
    return await _send(to=to_email, subject=subject, html=html)


def list_reports(db: Session, tenant_id: str, limit: int = 20) -> list[dict]:
    """Return recent reports summary (no HTML)."""
    rows = (
        db.query(AskHaipReport)
        .filter(AskHaipReport.tenant_id == tenant_id)
        .order_by(AskHaipReport.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "report_type": r.report_type,
            "title": r.title,
            "period_start": r.period_start,
            "period_end": r.period_end,
            "has_pdf": bool(r.pdf_s3_key),
            "email_sent_at": r.email_sent_at.isoformat() if r.email_sent_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
