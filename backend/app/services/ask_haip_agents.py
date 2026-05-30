"""
Ask HAIP — Phase 2: Analytics Agents

10 specialized agent processor functions. Each agent:
  - Takes raw data from existing HAIP analytics endpoints
  - Returns a structured AgentOutput with KPIs, findings, trend, concern
  - Is stateless and pure (no DB access, no HTTP calls)

The agent results feed the RCA engine with rich structured context
instead of raw JSON dumps.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Any
import math


# ─── Output Schema ────────────────────────────────────────────────────────────

@dataclass
class KPI:
    label: str
    value: Any                        # formatted string or number
    prev: Optional[Any] = None        # previous period value
    delta_pct: Optional[float] = None # % change (+/-)
    trend: str = "flat"               # up | down | flat
    unit: str = ""                    # ₹ | % | days | count
    severity: str = "normal"          # critical | warning | good | normal


@dataclass
class AgentOutput:
    agent: str                         # agent name
    domain: str                        # primary domain
    status: str = "ok"                 # ok | no_data | error
    kpis: list[KPI] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)   # evidence bullets
    top_concern: Optional[str] = None  # single most important signal
    top_positive: Optional[str] = None # best positive signal
    summary: str = ""                  # 1-sentence summary for LLM context
    charts: list[dict] = field(default_factory=list)    # chart specs
    metadata: dict = field(default_factory=dict)        # extra context


def _no_data(agent: str, domain: str) -> AgentOutput:
    return AgentOutput(agent=agent, domain=domain, status="no_data",
                       summary=f"No data available for {domain} analysis.")


def _fmt_inr(n: float) -> str:
    if n >= 10_000_000: return f"₹{n/10_000_000:.1f}Cr"
    if n >= 100_000:    return f"₹{n/100_000:.1f}L"
    if n >= 1_000:      return f"₹{n/1_000:.0f}k"
    return f"₹{n:.0f}"


def _delta(current: float, previous: float) -> tuple[float, str]:
    """Returns (delta_pct, trend) where trend is up/down/flat."""
    if not previous:
        return 0.0, "flat"
    pct = round((current - previous) / previous * 100, 1)
    trend = "up" if pct > 1 else ("down" if pct < -1 else "flat")
    return pct, trend


def _severity(delta_pct: float, inverse: bool = False) -> str:
    """Grade a delta as critical/warning/good/normal. inverse=True for metrics where down=good."""
    is_bad = delta_pct < 0 if not inverse else delta_pct > 0
    if is_bad:
        if abs(delta_pct) >= 20: return "critical"
        if abs(delta_pct) >= 10: return "warning"
    else:
        if abs(delta_pct) >= 10: return "good"
    return "normal"


# ─── Agent 1: Revenue Agent ───────────────────────────────────────────────────

def run_revenue_agent(raw_data: dict) -> AgentOutput:
    """Analyze revenue MTD, property breakdown, and forecast."""
    exec_d  = raw_data.get("/analytics/executive") or {}
    prop_d  = raw_data.get("/analytics/properties") or {}
    fcast_d = raw_data.get("/analytics/forecasting/revenue") or {}

    if not exec_d and not fcast_d:
        return _no_data("revenue", "revenue")

    # Core KPIs
    rev_mtd  = float(exec_d.get("revenue_mtd") or 0)
    rev_prev = float(exec_d.get("revenue_prev") or 0)
    rev_delta, rev_trend = _delta(rev_mtd, rev_prev)

    forecast     = float(fcast_d.get("full_month_forecast") or 0)
    ytd_actual   = float(fcast_d.get("ytd_actual") or 0)
    best_month   = fcast_d.get("best_month")
    best_rev     = float(fcast_d.get("best_month_revenue") or 0)

    kpis = [
        KPI("Revenue MTD", _fmt_inr(rev_mtd), _fmt_inr(rev_prev),
            rev_delta, rev_trend, "₹", _severity(rev_delta)),
        KPI("Full Month Forecast", _fmt_inr(forecast), unit="₹"),
        KPI("YTD Actual", _fmt_inr(ytd_actual), unit="₹"),
    ]

    # Property breakdown
    props = prop_d.get("properties", [])
    worst_prop = min(props, key=lambda p: p.get("revenue_mtd", 0), default=None) if props else None
    best_prop  = max(props, key=lambda p: p.get("revenue_mtd", 0), default=None) if props else None

    findings = []
    if rev_delta < -10:
        findings.append(f"Revenue dropped {abs(rev_delta):.1f}% vs prior period "
                        f"({_fmt_inr(rev_mtd)} vs {_fmt_inr(rev_prev)})")
    elif rev_delta > 10:
        findings.append(f"Revenue grew {rev_delta:.1f}% vs prior period ({_fmt_inr(rev_mtd)})")

    if worst_prop:
        findings.append(f"Lowest revenue property: {worst_prop.get('name','Unknown')} "
                        f"({_fmt_inr(float(worst_prop.get('revenue_mtd', 0)))})")
    if best_prop and best_prop != worst_prop:
        findings.append(f"Top revenue property: {best_prop.get('name','Unknown')} "
                        f"({_fmt_inr(float(best_prop.get('revenue_mtd', 0)))})")
    if forecast and rev_mtd:
        gap = forecast - rev_mtd
        findings.append(f"₹{_fmt_inr(gap)} remaining to hit full-month forecast of {_fmt_inr(forecast)}")

    top_concern  = findings[0] if findings and rev_delta < 0 else None
    top_positive = findings[0] if findings and rev_delta > 0 else None

    summary = (f"Revenue MTD: {_fmt_inr(rev_mtd)} ({'+' if rev_delta>0 else ''}{rev_delta:.1f}% vs prior). "
               f"Full-month forecast: {_fmt_inr(forecast)}.")

    # Chart spec — revenue daily trend
    rev_chart = exec_d.get("revenue_chart", [])
    charts = [{"type": "area", "label": "Revenue Trend", "series": rev_chart}] if rev_chart else []

    return AgentOutput(
        agent="revenue", domain="revenue",
        kpis=kpis, findings=findings,
        top_concern=top_concern, top_positive=top_positive,
        summary=summary, charts=charts,
        metadata={"best_month": best_month, "best_month_revenue": best_rev},
    )


# ─── Agent 2: Inquiry Agent ───────────────────────────────────────────────────

def run_inquiry_agent(raw_data: dict) -> AgentOutput:
    """Analyze inquiry volume, funnel conversion, SLA, and lost reasons."""
    exec_d  = raw_data.get("/analytics/executive") or {}
    daily_d = raw_data.get("/analytics/owner-daily") or {}

    if not exec_d:
        return _no_data("inquiry", "inquiry")

    active = int(exec_d.get("active_inquiries") or 0)
    funnel = exec_d.get("funnel", [])   # [{stage, count}]

    # Funnel conversion: NEW → BOOKED
    new_count    = next((s["count"] for s in funnel if s.get("stage") == "NEW"),    0)
    booked_count = next((s["count"] for s in funnel if s.get("stage") == "BOOKED"), 0)
    lost_count   = next((s["count"] for s in funnel if s.get("stage") == "LOST"),   0)
    ghosted_count= next((s["count"] for s in funnel if s.get("stage") == "GHOSTED"),0)
    total_funnel = max(new_count, 1)
    conversion   = round(booked_count / total_funnel * 100, 1) if total_funnel else 0

    sla_pct  = float(exec_d.get("sla_compliance_pct") or 0)
    today_q  = int(daily_d.get("today_queue") or 0)
    p95_resp = float(daily_d.get("p95_response_time_seconds") or 0)

    kpis = [
        KPI("Active Inquiries", active),
        KPI("Conversion Rate", f"{conversion}%", unit="%",
            severity="warning" if conversion < 20 else ("good" if conversion > 40 else "normal")),
        KPI("SLA Compliance", f"{sla_pct}%", unit="%",
            severity="critical" if sla_pct < 70 else ("warning" if sla_pct < 85 else "good")),
        KPI("Today's Queue", today_q,
            severity="warning" if today_q > 10 else "normal"),
        KPI("P95 Response Time", f"{int(p95_resp/60)}m" if p95_resp > 60 else f"{int(p95_resp)}s"),
    ]

    findings = []
    if conversion < 20:
        findings.append(f"Low funnel conversion: only {conversion}% of {new_count} inquiries convert to bookings")
    lost_total = lost_count + ghosted_count
    if lost_total:
        findings.append(f"{lost_total} inquiries lost/ghosted in the period ({lost_count} lost, {ghosted_count} ghosted)")
    if sla_pct < 80:
        findings.append(f"SLA compliance at {sla_pct}% — response time target being missed")
    if today_q > 5:
        findings.append(f"{today_q} inquiries in today's queue need attention")

    # Lost reason themes
    themes = daily_d.get("lost_reason_themes", [])
    if themes:
        top_theme = themes[0] if themes else {}
        if top_theme:
            findings.append(f"Top lost reason: '{top_theme.get('theme','unknown')}' "
                           f"({top_theme.get('count',0)} times)")

    top_concern = findings[0] if findings else None
    summary = (f"Active inquiries: {active}. Conversion: {conversion}%. "
               f"SLA compliance: {sla_pct}%. {lost_total} lost/ghosted.")

    charts = [{"type": "funnel", "label": "Inquiry Funnel", "series": funnel}] if funnel else []

    return AgentOutput(
        agent="inquiry", domain="inquiry",
        kpis=kpis, findings=findings,
        top_concern=top_concern, summary=summary, charts=charts,
    )


# ─── Agent 3: Guest Intelligence Agent ───────────────────────────────────────

def run_guest_agent(raw_data: dict) -> AgentOutput:
    """Analyze guest quality, LTV, churn risk, and cohort retention."""
    guest_d  = raw_data.get("/analytics/guests") or {}
    churn_d  = raw_data.get("/analytics/forecasting/churn") or {}
    cohort_d = raw_data.get("/analytics/forecasting/cohorts") or {}

    if not guest_d:
        return _no_data("guest_intelligence", "guest")

    total     = int(guest_d.get("total_guests") or 0)
    new_g     = int(guest_d.get("new_guests") or 0)
    repeat_pct= float(guest_d.get("repeat_pct") or 0)
    avg_ltv   = float(guest_d.get("avg_ltv") or 0)

    at_risk      = int(churn_d.get("total_at_risk") or 0)
    high_risk    = int(churn_d.get("high_risk_count") or 0)
    rev_at_risk  = float(churn_d.get("revenue_at_risk") or 0)

    overall_repeat = float(cohort_d.get("repeat_rate") or 0)
    vip_rate       = float(cohort_d.get("vip_rate") or 0)

    kpis = [
        KPI("Total Guests", total),
        KPI("New Guests (Period)", new_g),
        KPI("Repeat Rate", f"{repeat_pct}%", unit="%",
            severity="warning" if repeat_pct < 20 else ("good" if repeat_pct > 40 else "normal")),
        KPI("Avg LTV", _fmt_inr(avg_ltv), unit="₹"),
        KPI("Churn Risk: High", high_risk,
            severity="critical" if high_risk > 10 else ("warning" if high_risk > 5 else "normal")),
        KPI("Revenue at Risk", _fmt_inr(rev_at_risk), unit="₹",
            severity="critical" if rev_at_risk > 500_000 else "normal"),
        KPI("VIP Rate", f"{vip_rate}%", unit="%"),
    ]

    findings = []
    if high_risk > 5:
        findings.append(f"{high_risk} guests at high churn risk — {_fmt_inr(rev_at_risk)} revenue exposure")
    if repeat_pct < 20:
        findings.append(f"Low repeat guest rate ({repeat_pct}%) — retention strategy needed")
    if at_risk > 0:
        findings.append(f"{at_risk} total guests haven't been contacted in 45+ days")
    if overall_repeat:
        findings.append(f"Overall cohort repeat rate: {overall_repeat}% — "
                       f"{'strong' if overall_repeat > 35 else 'needs improvement'}")
    if vip_rate:
        findings.append(f"VIP guests (silver/gold/platinum): {vip_rate}% of total base")

    top_concern  = findings[0] if findings and high_risk > 5 else None
    top_positive = f"Repeat rate {repeat_pct}% — healthy retention" if repeat_pct > 35 else None

    summary = (f"Guest base: {total} total, {new_g} new. Repeat rate: {repeat_pct}%. "
               f"Avg LTV: {_fmt_inr(avg_ltv)}. {high_risk} high-risk churn guests.")

    return AgentOutput(
        agent="guest_intelligence", domain="guest",
        kpis=kpis, findings=findings,
        top_concern=top_concern, top_positive=top_positive,
        summary=summary,
    )


# ─── Agent 4: Occupancy Agent ─────────────────────────────────────────────────

def run_occupancy_agent(raw_data: dict) -> AgentOutput:
    """Analyze portfolio occupancy, property heatmap, and forecast."""
    exec_d  = raw_data.get("/analytics/executive") or {}
    fcast_d = raw_data.get("/analytics/forecasting/occupancy") or {}

    if not exec_d:
        return _no_data("occupancy", "occupancy")

    occ_pct  = float(exec_d.get("occupancy_pct") or 0)
    occ_prev = float(exec_d.get("occupancy_prev") or 0)
    occ_delta, occ_trend = _delta(occ_pct, occ_prev)

    forecast_30d = float(fcast_d.get("portfolio_forecast_30d") or 0)
    peak_date    = fcast_d.get("highest_demand_date")
    low_date     = fcast_d.get("lowest_demand_date")

    kpis = [
        KPI("Portfolio Occupancy", f"{occ_pct}%", f"{occ_prev}%",
            occ_delta, occ_trend, "%", _severity(occ_delta)),
        KPI("30-Day Forecast", f"{forecast_30d}%", unit="%",
            severity="critical" if forecast_30d < 40 else ("warning" if forecast_30d < 60 else "good")),
    ]
    if peak_date:
        kpis.append(KPI("Peak Demand Date", peak_date))
    if low_date:
        kpis.append(KPI("Lowest Demand Date", low_date))

    # Per-property heatmap
    heatmap = exec_d.get("occupancy_heatmap", [])
    worst_prop = min(heatmap, key=lambda p: p.get("pct", 100), default=None) if heatmap else None
    best_prop  = max(heatmap, key=lambda p: p.get("pct", 0),   default=None) if heatmap else None

    findings = []
    if occ_pct < 40:
        findings.append(f"CRITICAL: Portfolio occupancy very low at {occ_pct}% "
                        f"({'+' if occ_delta>0 else ''}{occ_delta:.1f}% vs prior)")
    elif occ_pct < 60:
        findings.append(f"Occupancy below target: {occ_pct}% ({occ_delta:+.1f}% vs prior)")
    if worst_prop:
        findings.append(f"Lowest occupancy: {worst_prop.get('name','Unknown')} at {worst_prop.get('pct',0):.1f}%")
    if best_prop:
        findings.append(f"Highest occupancy: {best_prop.get('name','Unknown')} at {best_prop.get('pct',0):.1f}%")
    if forecast_30d < occ_pct - 5:
        findings.append(f"Occupancy forecast trending down: {occ_pct}% → {forecast_30d}%")

    top_concern  = findings[0] if findings and occ_pct < 60 else None
    top_positive = f"Occupancy {occ_pct}% — above 70% target" if occ_pct >= 70 else None

    summary = (f"Portfolio occupancy: {occ_pct}% ({occ_delta:+.1f}% vs prior). "
               f"30-day forecast: {forecast_30d}%.")

    charts = [{"type": "heatmap", "label": "Property Occupancy", "series": heatmap}] if heatmap else []

    return AgentOutput(
        agent="occupancy", domain="occupancy",
        kpis=kpis, findings=findings,
        top_concern=top_concern, top_positive=top_positive,
        summary=summary, charts=charts,
    )


# ─── Agent 5: Property Performance Agent ─────────────────────────────────────

def run_property_agent(raw_data: dict) -> AgentOutput:
    """Multi-property benchmarking: RevPAR, ADR, direct vs OTA split."""
    prop_d   = raw_data.get("/analytics/properties") or {}
    price_d  = raw_data.get("/analytics/forecasting/pricing") or {}

    if not prop_d:
        return _no_data("property_performance", "property")

    portfolio_occ = float(prop_d.get("portfolio_occupancy") or 0)
    portfolio_rev = float(prop_d.get("portfolio_revenue_mtd") or 0)
    portfolio_adr = float(prop_d.get("portfolio_adr") or 0)
    props = prop_d.get("properties", [])

    kpis = [
        KPI("Portfolio Revenue MTD", _fmt_inr(portfolio_rev), unit="₹"),
        KPI("Portfolio ADR", _fmt_inr(portfolio_adr), unit="₹"),
        KPI("Portfolio Occupancy", f"{portfolio_occ}%", unit="%"),
        KPI("Properties Tracked", len(props)),
    ]

    findings = []
    # Rank by RevPAR
    ranked = sorted(props, key=lambda p: float(p.get("revpar", 0) or 0))
    if ranked:
        worst = ranked[0]
        best  = ranked[-1]
        findings.append(f"Best RevPAR: {best.get('name','?')} "
                       f"({_fmt_inr(float(best.get('revpar',0) or 0))})")
        if len(ranked) > 1:
            findings.append(f"Lowest RevPAR: {worst.get('name','?')} "
                           f"({_fmt_inr(float(worst.get('revpar',0) or 0))}) — needs attention")

    # OTA vs direct split
    high_ota = [p for p in props if float(p.get("ota_pct", 0) or 0) > 60]
    if high_ota:
        findings.append(f"{len(high_ota)} propert{'y' if len(high_ota)==1 else 'ies'} "
                       f"over-reliant on OTA (>60%) — commission drain")

    # Pricing suggestions
    suggestions = price_d.get("suggestions", [])
    up_count  = price_d.get("properties_suggesting_increase", 0)
    down_count= price_d.get("properties_suggesting_decrease", 0)
    avg_uplift= float(price_d.get("avg_suggested_uplift_pct") or 0)
    if suggestions:
        findings.append(f"Dynamic pricing: {up_count} properties can increase rate "
                       f"(avg +{avg_uplift:.1f}%), {down_count} should discount")

    top_concern  = findings[1] if len(findings) > 1 else None
    summary = (f"{len(props)} properties. Portfolio ADR: {_fmt_inr(portfolio_adr)}, "
               f"RevPAR varies. {len(high_ota)} OTA-dependent properties.")

    charts = [{"type": "bar", "label": "RevPAR by Property", "series": [
        {"name": p.get("name","?"), "value": float(p.get("revpar",0) or 0)} for p in ranked
    ]}]

    return AgentOutput(
        agent="property_performance", domain="property",
        kpis=kpis, findings=findings,
        top_concern=top_concern, summary=summary, charts=charts,
    )


# ─── Agent 6: Channel Analytics Agent ────────────────────────────────────────

def run_channel_agent(raw_data: dict) -> AgentOutput:
    """Analyze channel performance: delivery, response time, conversion."""
    ch_d  = raw_data.get("/analytics/channels") or {}
    att_d = raw_data.get("/analytics/attribution") or {}

    if not ch_d:
        return _no_data("channel_analytics", "channel")

    delivery   = float(ch_d.get("delivery_rate_pct") or 0)
    read_rate  = float(ch_d.get("read_rate_pct") or 0)
    resp_time  = float(ch_d.get("avg_response_time_s") or 0)
    ai_accept  = float(ch_d.get("ai_acceptance_pct") or 0)
    total_msgs = int(ch_d.get("total_messages") or 0)

    # Attribution
    top_first = att_d.get("top_first_touch")
    top_last  = att_d.get("top_last_touch")
    fastest_ch= att_d.get("fastest_channel")
    avg_days  = float(att_d.get("avg_days_to_convert") or 0)

    kpis = [
        KPI("Delivery Rate", f"{delivery}%", unit="%",
            severity="critical" if delivery < 85 else ("warning" if delivery < 92 else "good")),
        KPI("Read Rate", f"{read_rate}%", unit="%"),
        KPI("Avg Response Time", f"{int(resp_time/60)}m" if resp_time > 60 else f"{int(resp_time)}s",
            severity="warning" if resp_time > 300 else "normal"),
        KPI("AI Acceptance", f"{ai_accept}%", unit="%"),
        KPI("Total Messages", total_msgs),
    ]
    if top_first:
        kpis.append(KPI("Top First-Touch Channel", top_first))
    if fastest_ch:
        kpis.append(KPI("Fastest to Convert", fastest_ch))

    findings = []
    if delivery < 90:
        findings.append(f"WhatsApp delivery rate low at {delivery}% — check phone number health")
    if resp_time > 300:
        mins = int(resp_time/60)
        findings.append(f"Average response time {mins}m — guests may be dropping off")
    if top_first:
        first_rows = att_d.get("first_touch_breakdown", [])
        top_row = next((r for r in first_rows if r.get("source") == top_first), {})
        rev = float(top_row.get("revenue", 0) or 0)
        findings.append(f"Top acquisition channel: {top_first} "
                       f"({top_row.get('conversion_pct',0):.1f}% CVR, {_fmt_inr(rev)} revenue)")
    if avg_days:
        findings.append(f"Average days to convert: {avg_days:.1f} days "
                       f"(fastest channel: {fastest_ch or 'unknown'})")
    if ai_accept < 50:
        findings.append(f"AI draft acceptance low ({ai_accept}%) — consider updating AI tone/templates")

    # Channel breakdown
    ch_breakdown = ch_d.get("channel_breakdown", [])
    charts = [{"type": "bar", "label": "Channel Volume", "series": ch_breakdown}] if ch_breakdown else []

    top_concern  = findings[0] if findings and delivery < 90 else None
    summary = (f"Delivery: {delivery}%, Read: {read_rate}%. "
               f"Top source: {top_first}. Avg {avg_days:.1f}d to convert.")

    return AgentOutput(
        agent="channel_analytics", domain="channel",
        kpis=kpis, findings=findings,
        top_concern=top_concern, summary=summary, charts=charts,
    )


# ─── Agent 7: Campaign Analytics Agent ───────────────────────────────────────

def run_campaign_agent(raw_data: dict) -> AgentOutput:
    """Analyze WhatsApp campaign performance and subscriber health."""
    camp_d = raw_data.get("/analytics/campaigns") or {}

    if not camp_d:
        return _no_data("campaign_analytics", "campaign")

    total_camps   = int(camp_d.get("total_campaigns") or 0)
    active_camps  = int(camp_d.get("active_campaigns") or 0)
    avg_delivery  = float(camp_d.get("avg_delivery_rate") or 0)
    avg_read      = float(camp_d.get("avg_read_rate") or 0)
    subscriber_ct = int(camp_d.get("subscriber_count") or 0)

    kpis = [
        KPI("Total Campaigns", total_camps),
        KPI("Active Campaigns", active_camps),
        KPI("Avg Delivery Rate", f"{avg_delivery}%", unit="%",
            severity="critical" if avg_delivery < 85 else "good"),
        KPI("Avg Read Rate", f"{avg_read}%", unit="%",
            severity="warning" if avg_read < 30 else "good"),
        KPI("Subscribers", subscriber_ct),
    ]

    findings = []
    # Top performing template
    templates = camp_d.get("template_performance", [])
    if templates:
        best_tmpl = max(templates, key=lambda t: float(t.get("read_rate", 0) or 0), default=None)
        if best_tmpl:
            findings.append(f"Best template: '{best_tmpl.get('name','?')}' "
                           f"({best_tmpl.get('read_rate',0):.1f}% read rate)")
        worst_tmpl = min(templates, key=lambda t: float(t.get("delivery_rate", 0) or 100), default=None)
        if worst_tmpl and float(worst_tmpl.get("delivery_rate", 100) or 100) < 80:
            findings.append(f"Low delivery template: '{worst_tmpl.get('name','?')}' "
                           f"({worst_tmpl.get('delivery_rate',0):.1f}%) — may need Meta re-approval")

    if avg_read < 30:
        findings.append(f"Average campaign read rate low ({avg_read}%) — review send timing and content")
    if subscriber_ct < 100:
        findings.append(f"Small subscriber base ({subscriber_ct}) — grow list for campaign impact")

    # Subscriber trend
    sub_trend = camp_d.get("subscriber_trend", [])
    charts = [{"type": "line", "label": "Subscriber Growth", "series": sub_trend}] if sub_trend else []

    top_concern = findings[-1] if findings and avg_read < 30 else None
    summary = (f"{total_camps} campaigns ({active_camps} active). "
               f"Avg delivery: {avg_delivery}%, read: {avg_read}%. {subscriber_ct} subscribers.")

    return AgentOutput(
        agent="campaign_analytics", domain="campaign",
        kpis=kpis, findings=findings,
        top_concern=top_concern, summary=summary, charts=charts,
    )


# ─── Agent 8: Intent Intelligence Agent ──────────────────────────────────────

def run_intent_agent(raw_data: dict) -> AgentOutput:
    """Analyze travel intent distribution, conversion, and revenue by intent."""
    int_d = raw_data.get("/analytics/intent") or {}

    if not int_d:
        return _no_data("intent_intelligence", "intent")

    total_classified = int(int_d.get("total_classified") or 0)
    top_intent       = int_d.get("top_intent")
    top_cvr          = float(int_d.get("top_intent_conversion") or 0)
    top_rev_intent   = int_d.get("top_revenue_intent")
    top_rev_value    = float(int_d.get("top_revenue_intent_value") or 0)

    distribution = int_d.get("intent_distribution", [])

    kpis = [
        KPI("Classified Inquiries", total_classified),
    ]
    if top_intent:
        kpis.append(KPI("Top Converting Intent", top_intent.replace("_"," ").title(),
                        unit="", severity="good"))
        kpis.append(KPI("Top Intent CVR", f"{top_cvr}%", unit="%"))
    if top_rev_intent:
        kpis.append(KPI("Top Revenue Intent", top_rev_intent.replace("_"," ").title()))
        kpis.append(KPI("Revenue from Top Intent", _fmt_inr(top_rev_value), unit="₹"))

    findings = []
    if top_intent:
        findings.append(f"Highest converting intent: {top_intent.replace('_',' ').title()} "
                       f"({top_cvr:.1f}% CVR)")
    if top_rev_intent and top_rev_intent != top_intent:
        findings.append(f"Highest revenue intent: {top_rev_intent.replace('_',' ').title()} "
                       f"({_fmt_inr(top_rev_value)})")

    # Declining intent
    trend = int_d.get("intent_trend", [])
    if distribution:
        # Flag intents with < 5% share
        minor = [b for b in distribution if float(b.get("conversion_pct", 0) or 0) < 5]
        if minor:
            minor_names = ", ".join(b["intent"].replace("_"," ").title() for b in minor[:3])
            findings.append(f"Low-converting intents: {minor_names} (< 5% CVR)")
        # High value intents
        high_val = [b for b in distribution if float(b.get("avg_booking_value", 0) or 0) > 200_000]
        if high_val:
            findings.append(f"{len(high_val)} intent(s) with avg booking >₹2L: "
                           f"{', '.join(b['intent'].replace('_',' ').title() for b in high_val[:2])}")

    charts = [{"type": "pie", "label": "Intent Distribution", "series": [
        {"name": b.get("intent","?").replace("_"," ").title(),
         "value": b.get("count", 0)}
        for b in distribution
    ]}] if distribution else []

    top_positive = findings[0] if findings else None
    summary = (f"{total_classified} inquiries classified. "
               f"Top intent: {(top_intent or 'unknown').replace('_',' ').title()} at {top_cvr:.1f}% CVR.")

    return AgentOutput(
        agent="intent_intelligence", domain="intent",
        kpis=kpis, findings=findings,
        top_positive=top_positive, summary=summary, charts=charts,
    )


# ─── Agent 9: Objection Intelligence Agent ───────────────────────────────────

def run_objection_agent(raw_data: dict) -> AgentOutput:
    """Analyze lost-booking objections: Pareto, revenue lost, competitor intelligence."""
    obj_d = raw_data.get("/analytics/objections") or {}

    if not obj_d:
        return _no_data("objection_intelligence", "objection")

    total_lost    = int(obj_d.get("total_lost") or 0)
    total_rev_lost= float(obj_d.get("total_revenue_lost") or 0)
    top_obj       = obj_d.get("top_objection")
    budget_pct    = float(obj_d.get("budget_objection_pct") or 0)
    comp_mentions = int(obj_d.get("competitor_mention_count") or 0)

    objections = obj_d.get("objections", [])
    competitors = obj_d.get("competitors", [])

    kpis = [
        KPI("Total Lost Inquiries", total_lost),
        KPI("Revenue Lost", _fmt_inr(total_rev_lost), unit="₹",
            severity="critical" if total_rev_lost > 500_000 else "warning"),
        KPI("Budget Objection Rate", f"{budget_pct}%", unit="%",
            severity="critical" if budget_pct > 40 else ("warning" if budget_pct > 25 else "normal")),
        KPI("Competitor Mentions", comp_mentions,
            severity="warning" if comp_mentions > 10 else "normal"),
    ]

    findings = []
    if top_obj:
        top_row = next((o for o in objections if o.get("code") == top_obj), {})
        findings.append(f"Top objection: '{top_row.get('label', top_obj)}' "
                       f"— {top_row.get('count',0)} times, "
                       f"{_fmt_inr(float(top_row.get('revenue_lost',0) or 0))} revenue lost")
    if budget_pct > 30:
        findings.append(f"HIGH price sensitivity: {budget_pct:.0f}% of objections are budget-related")
    if comp_mentions > 5:
        top_comp = competitors[0] if competitors else {}
        findings.append(f"{comp_mentions} competitor mentions — "
                       f"'{top_comp.get('name','unknown')}' mentioned most frequently")
    if total_rev_lost > 200_000:
        findings.append(f"{_fmt_inr(total_rev_lost)} total revenue lost to objections this period")

    # Pareto: top 3 objections
    top3 = sorted(objections, key=lambda o: float(o.get("revenue_lost", 0) or 0), reverse=True)[:3]
    charts = [{"type": "bar", "label": "Objection Revenue Lost", "series": [
        {"name": o.get("label","?"), "value": float(o.get("revenue_lost",0) or 0)}
        for o in top3
    ]}] if top3 else []

    top_concern = findings[0] if findings else None
    summary = (f"{total_lost} lost inquiries, {_fmt_inr(total_rev_lost)} revenue lost. "
               f"Budget objections: {budget_pct:.0f}%. {comp_mentions} competitor mentions.")

    return AgentOutput(
        agent="objection_intelligence", domain="objection",
        kpis=kpis, findings=findings,
        top_concern=top_concern, summary=summary, charts=charts,
        metadata={"top_competitors": [c.get("name") for c in competitors[:3]]},
    )


# ─── Agent 10: Attribution Agent ─────────────────────────────────────────────

def run_attribution_agent(raw_data: dict) -> AgentOutput:
    """Analyze booking attribution: first/last touch channels, journey paths."""
    att_d = raw_data.get("/analytics/attribution") or {}

    if not att_d:
        return _no_data("attribution", "attribution")

    total_bookings = int(att_d.get("total_bookings") or 0)
    avg_touchpoints= float(att_d.get("avg_touchpoints") or 0)
    avg_days       = float(att_d.get("avg_days_to_convert") or 0)
    top_first      = att_d.get("top_first_touch")
    top_first_rev  = float(att_d.get("top_first_touch_revenue") or 0)
    top_last       = att_d.get("top_last_touch")
    top_last_rev   = float(att_d.get("top_last_touch_revenue") or 0)
    fastest        = att_d.get("fastest_channel")

    kpis = [
        KPI("Total Bookings", total_bookings),
        KPI("Avg Touchpoints", f"{avg_touchpoints:.1f}"),
        KPI("Avg Days to Convert", f"{avg_days:.1f}d"),
    ]
    if top_first:
        kpis.append(KPI("Top First-Touch", top_first, unit=""))
        kpis.append(KPI("First-Touch Revenue", _fmt_inr(top_first_rev), unit="₹"))
    if top_last:
        kpis.append(KPI("Top Last-Touch (Closer)", top_last, unit=""))
    if fastest:
        kpis.append(KPI("Fastest Channel", fastest))

    findings = []
    if top_first:
        findings.append(f"Top booking source (first touch): {top_first} "
                       f"— {_fmt_inr(top_first_rev)} attributed revenue")
    if top_last and top_last != top_first:
        findings.append(f"Top closing channel (last touch): {top_last} "
                       f"— {_fmt_inr(top_last_rev)} attributed revenue")
    if top_first == top_last:
        findings.append(f"Single-channel journeys dominate — {top_first} both discovers and closes")
    if avg_days > 7:
        findings.append(f"Long conversion journey: {avg_days:.1f} days avg — "
                       f"consider faster follow-up workflows")
    if fastest:
        findings.append(f"Fastest converting channel: {fastest} — invest here for quick wins")

    journey_paths = att_d.get("journey_paths", [])
    if journey_paths:
        top_path = journey_paths[0]
        findings.append(f"Most common journey: '{top_path.get('path','?')}' "
                       f"({top_path.get('count',0)} bookings, "
                       f"{top_path.get('conversion_pct',0):.1f}% CVR)")

    charts = []
    first_breakdown = att_d.get("first_touch_breakdown", [])
    if first_breakdown:
        charts.append({"type": "bar", "label": "First-Touch Revenue", "series": [
            {"name": r.get("source","?"), "value": float(r.get("revenue",0) or 0)}
            for r in first_breakdown[:6]
        ]})

    top_positive = findings[0] if findings else None
    summary = (f"{total_bookings} bookings. Top source: {top_first}. "
               f"Avg {avg_touchpoints:.1f} touchpoints, {avg_days:.1f} days to convert.")

    return AgentOutput(
        agent="attribution", domain="attribution",
        kpis=kpis, findings=findings,
        top_positive=top_positive, summary=summary, charts=charts,
    )


# ─── Agent Router ─────────────────────────────────────────────────────────────

AGENT_PROCESSORS = {
    "revenue":     run_revenue_agent,
    "occupancy":   run_occupancy_agent,
    "inquiry":     run_inquiry_agent,
    "guest":       run_guest_agent,
    "channel":     run_channel_agent,
    "campaign":    run_campaign_agent,
    "property":    run_property_agent,
    "objection":   run_objection_agent,
    "intent":      run_intent_agent,
    "attribution": run_attribution_agent,
}


def process_agents(domains: list[str], raw_data: dict) -> dict[str, dict]:
    """
    Run agent processors for all detected domains.
    Returns: dict[domain → AgentOutput as dict]
    """
    results: dict[str, dict] = {}
    seen: set[str] = set()

    for domain in domains:
        if domain in AGENT_PROCESSORS and domain not in seen:
            try:
                output: AgentOutput = AGENT_PROCESSORS[domain](raw_data)
                results[domain] = asdict(output)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Agent %s failed: %s", domain, e)
                results[domain] = asdict(_no_data(domain, domain))
            seen.add(domain)

    return results


def agents_to_llm_context(agent_outputs: dict[str, dict]) -> str:
    """
    Convert structured agent outputs to a concise LLM context string.
    Each agent gets: summary + top concern + key findings.
    """
    lines = []
    for domain, output in agent_outputs.items():
        if output.get("status") == "no_data":
            lines.append(f"[{domain.upper()}]: No data available")
            continue

        lines.append(f"[{domain.upper()} AGENT]")
        lines.append(f"  Summary: {output.get('summary','')}")

        concern = output.get("top_concern")
        if concern:
            lines.append(f"  ⚠ Top concern: {concern}")

        positive = output.get("top_positive")
        if positive:
            lines.append(f"  ✓ Positive: {positive}")

        findings = output.get("findings", [])
        for f in findings[:4]:  # cap at 4 per agent to control token usage
            lines.append(f"  • {f}")

        kpis = output.get("kpis", [])
        critical_kpis = [k for k in kpis if k.get("severity") in ("critical", "warning")]
        for k in critical_kpis[:3]:
            lines.append(f"  KPI [{k.get('severity','').upper()}] {k.get('label')}: {k.get('value')}"
                        + (f" (was {k.get('prev')}, {k.get('delta_pct',0):+.1f}%)" if k.get('prev') else ""))

        lines.append("")

    return "\n".join(lines)
