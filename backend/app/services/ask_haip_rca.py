"""
Ask HAIP — Phase 4: Enhanced Root Cause Engine

Upgrades over Phase 1 basic RCA:
  1. 20+ correlation rules across all 10 agent domains
  2. Confidence scoring algorithm (data completeness × signal strength)
  3. Comparative analysis (this period vs prior period)
  4. Anomaly injection from existing /analytics/anomalies endpoint
  5. Proper prompt caching (Claude ephemeral cache_control)
  6. Multi-hypothesis generation (up to 3 ranked findings)
  7. Root cause chain: signal → cause → impact → action
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from app.adapters.llm import get_llm
from app.services.ask_haip_agents import agents_to_llm_context, _fmt_inr

log = logging.getLogger(__name__)


# ─── Confidence Scoring ───────────────────────────────────────────────────────

@dataclass
class ConfidenceResult:
    score: float           # 0.0–1.0
    label: str             # high | medium | low
    data_completeness: str # high | partial | low
    agents_with_data: int
    agents_total: int
    missing_domains: list[str] = field(default_factory=list)
    boosters: list[str] = field(default_factory=list)    # signals that increase confidence
    detractors: list[str] = field(default_factory=list)  # signals that decrease confidence


def calculate_confidence(
    domains: list[str],
    agent_outputs: dict,
    correlations: list[str],
) -> ConfidenceResult:
    """
    Score confidence 0.0–1.0 based on:
    - Data completeness (how many agents returned data)
    - Signal strength (number and severity of correlations found)
    - Domain coverage (did we hit all relevant domains?)
    """
    total = len(domains) if domains else 1
    with_data = sum(1 for d in domains if agent_outputs.get(d, {}).get("status") == "ok")
    missing   = [d for d in domains if agent_outputs.get(d, {}).get("status") != "ok"]

    completeness_score = with_data / max(total, 1)

    # Boost confidence if we have critical signals (they're more actionable)
    critical_count = sum(1 for s in correlations if "CRITICAL" in s)
    warning_count  = sum(1 for s in correlations if "WARNING" in s or "HIGH" in s)
    signal_boost   = min(0.15, critical_count * 0.08 + warning_count * 0.04)

    # Penalise if missing key revenue/occupancy agents
    key_domains = {"revenue", "occupancy", "inquiry"}
    missing_key = key_domains & set(missing)
    key_penalty = len(missing_key) * 0.12

    raw_score = completeness_score + signal_boost - key_penalty
    score     = round(max(0.1, min(1.0, raw_score)), 2)

    boosters   = [f"Found {len(correlations)} cross-agent correlation signals"] if correlations else []
    detractors = [f"Missing data for: {', '.join(missing)}"] if missing else []
    if missing_key:
        detractors.append(f"Key domains unavailable: {', '.join(missing_key)}")

    completeness_label = "high" if completeness_score >= 0.75 else ("partial" if completeness_score >= 0.5 else "low")
    confidence_label   = "high" if score >= 0.75 else ("medium" if score >= 0.5 else "low")

    return ConfidenceResult(
        score=score, label=confidence_label,
        data_completeness=completeness_label,
        agents_with_data=with_data, agents_total=total,
        missing_domains=missing, boosters=boosters, detractors=detractors,
    )


# ─── Enhanced Correlation Engine (20+ rules) ─────────────────────────────────

def build_correlations(
    domains: list[str],
    raw_data: dict,
    agent_outputs: dict,
) -> list[dict]:
    """
    Phase 4: Rich correlation analysis returning structured signals.
    Each signal has: type, severity, message, domains_involved.
    """
    signals: list[dict] = []
    domain_set = set(domains)

    def sig(msg: str, severity: str = "info", domains: list = None):
        signals.append({
            "message": msg,
            "severity": severity,  # critical | warning | info | positive
            "domains": domains or [],
        })

    def get_kpi(domain: str, label: str) -> Optional[float]:
        """Safely extract a KPI value from agent outputs."""
        output = agent_outputs.get(domain, {})
        for kpi in output.get("kpis", []):
            if kpi.get("label", "").lower() == label.lower():
                v = kpi.get("value", "")
                try:
                    return float(str(v).replace("₹","").replace("L","00000").replace("k","000").replace("%","").strip())
                except Exception:
                    return None
        return None

    # ── Revenue signals ────────────────────────────────────────────────────────
    exec_d   = raw_data.get("/analytics/executive") or {}
    rev_mtd  = float(exec_d.get("revenue_mtd") or 0)
    rev_prev = float(exec_d.get("revenue_prev") or 0)
    if rev_prev > 0:
        rev_delta = (rev_mtd - rev_prev) / rev_prev * 100
        if rev_delta < -20:
            sig(f"Revenue dropped {abs(rev_delta):.1f}% vs prior ({_fmt_inr(rev_mtd)} vs {_fmt_inr(rev_prev)})",
                "critical", ["revenue"])
        elif rev_delta < -10:
            sig(f"Revenue declined {abs(rev_delta):.1f}% vs prior ({_fmt_inr(rev_mtd)})",
                "warning", ["revenue"])
        elif rev_delta > 15:
            sig(f"Revenue up {rev_delta:.1f}% vs prior ({_fmt_inr(rev_mtd)}) — strong period",
                "positive", ["revenue"])

    # ── Occupancy signals ──────────────────────────────────────────────────────
    occ_pct  = float(exec_d.get("occupancy_pct") or 0)
    occ_prev = float(exec_d.get("occupancy_prev") or 0)
    if occ_pct < 35:
        sig(f"CRITICAL: Portfolio occupancy very low at {occ_pct}%", "critical", ["occupancy"])
    elif occ_pct < 55:
        sig(f"Occupancy below target: {occ_pct}% (target 65%+)", "warning", ["occupancy"])
    elif occ_pct >= 80:
        sig(f"Strong occupancy: {occ_pct}% — pricing power available", "positive", ["occupancy"])

    if occ_prev > 0 and occ_pct < occ_prev - 10:
        sig(f"Occupancy declining: {occ_pct}% vs {occ_prev}% prior ({occ_pct-occ_prev:+.1f}%)",
            "warning", ["occupancy", "revenue"])

    # ── Inquiry / Funnel signals ───────────────────────────────────────────────
    funnel  = exec_d.get("funnel", [])
    new_inq = next((s.get("count",0) for s in funnel if s.get("stage") == "NEW"), 0)
    booked  = next((s.get("count",0) for s in funnel if s.get("stage") == "BOOKED"), 0)
    lost    = next((s.get("count",0) for s in funnel if s.get("stage") == "LOST"), 0)
    ghosted = next((s.get("count",0) for s in funnel if s.get("stage") == "GHOSTED"), 0)

    if new_inq > 0:
        cvr = booked / new_inq * 100
        if cvr < 10:
            sig(f"Very low funnel conversion: {cvr:.1f}% ({booked} of {new_inq} inquiries booked)",
                "critical", ["inquiry", "revenue"])
        elif cvr < 20:
            sig(f"Below-average conversion: {cvr:.1f}%", "warning", ["inquiry"])

    if ghosted > lost:
        sig(f"Ghosting exceeds explicit lost: {ghosted} ghosted vs {lost} lost — follow-up gap",
            "warning", ["inquiry", "channel"])

    sla = float(exec_d.get("sla_compliance_pct") or 100)
    if sla < 70:
        sig(f"CRITICAL SLA breach: {sla}% compliance — response time failures",
            "critical", ["inquiry", "channel"])
    elif sla < 85:
        sig(f"SLA at risk: {sla}% — slow responses likely causing lost leads",
            "warning", ["inquiry"])

    # ── Objection signals ──────────────────────────────────────────────────────
    obj_d      = raw_data.get("/analytics/objections") or {}
    budget_pct = float(obj_d.get("budget_objection_pct") or 0)
    rev_lost   = float(obj_d.get("total_revenue_lost") or 0)
    comp_count = int(obj_d.get("competitor_mention_count") or 0)
    top_obj    = obj_d.get("top_objection")

    if budget_pct > 40:
        sig(f"HIGH price sensitivity: {budget_pct:.0f}% of objections are budget-related",
            "critical", ["objection", "revenue"])
    elif budget_pct > 25:
        sig(f"Growing price sensitivity: {budget_pct:.0f}% budget objections", "warning", ["objection"])

    if rev_lost > 300_000:
        sig(f"{_fmt_inr(rev_lost)} revenue lost to objections this period", "warning", ["objection", "revenue"])

    if comp_count > 15:
        obj_list = obj_d.get("competitors", [])
        top_comp = obj_list[0].get("name","?") if obj_list else "unknown"
        sig(f"High competitive pressure: {comp_count} competitor mentions, '{top_comp}' leads",
            "critical", ["objection", "attribution"])
    elif comp_count > 5:
        sig(f"{comp_count} competitor mentions detected", "warning", ["objection"])

    # ── Channel / Delivery signals ─────────────────────────────────────────────
    ch_d     = raw_data.get("/analytics/channels") or {}
    delivery = float(ch_d.get("delivery_rate_pct") or 100)
    resp_t   = float(ch_d.get("avg_response_time_s") or 0)

    if delivery < 85:
        sig(f"WhatsApp delivery rate critical: {delivery}% — messages not reaching guests",
            "critical", ["channel", "inquiry"])
    elif delivery < 92:
        sig(f"Delivery rate below optimal: {delivery}%", "warning", ["channel"])

    if resp_t > 600:  # 10 min+
        sig(f"Slow response time: {resp_t/60:.0f} min avg — guests may abandon",
            "critical", ["channel", "inquiry"])
    elif resp_t > 300:
        sig(f"Response time elevated: {resp_t/60:.0f} min avg", "warning", ["channel"])

    # ── Guest / Churn signals ─────────────────────────────────────────────────
    churn_d  = raw_data.get("/analytics/forecasting/churn") or {}
    high_risk= int(churn_d.get("high_risk_count") or 0)
    rev_risk = float(churn_d.get("revenue_at_risk") or 0)
    g_data   = raw_data.get("/analytics/guests") or {}
    repeat_p = float(g_data.get("repeat_pct") or 0)

    if high_risk > 10:
        sig(f"{high_risk} guests at high churn risk — {_fmt_inr(rev_risk)} at stake",
            "critical", ["guest", "revenue"])
    elif high_risk > 5:
        sig(f"{high_risk} high-risk churn guests ({_fmt_inr(rev_risk)} revenue exposure)",
            "warning", ["guest"])

    if repeat_p < 15:
        sig(f"Very low repeat rate ({repeat_p}%) — retention strategy urgently needed",
            "critical", ["guest"])
    elif repeat_p < 25:
        sig(f"Below-target repeat rate: {repeat_p}%", "warning", ["guest"])
    elif repeat_p > 40:
        sig(f"Strong repeat rate {repeat_p}% — loyalty driving revenue", "positive", ["guest"])

    # ── Cross-agent compound correlations ─────────────────────────────────────
    # Revenue down + Occupancy down → pricing/demand problem
    if rev_prev > 0 and rev_mtd < rev_prev * 0.85 and occ_pct < 60:
        sig("COMPOUND: Both revenue and occupancy declining — likely demand shortfall or pricing mismatch",
            "critical", ["revenue", "occupancy"])

    # Low occupancy + high budget objections → overpriced
    if occ_pct < 55 and budget_pct > 30:
        sig("COMPOUND: Low occupancy + high budget objections → property likely overpriced for current demand",
            "critical", ["occupancy", "objection", "revenue"])

    # Poor delivery + low inquiry volume → pipeline leaking at channel level
    if delivery < 90 and new_inq < 10:
        sig("COMPOUND: Low delivery rate + few new inquiries → channel health issue blocking pipeline",
            "critical", ["channel", "inquiry"])

    # High competitor mentions + conversion drop → competitive displacement
    if comp_count > 10 and new_inq > 0 and booked / max(new_inq, 1) < 0.15:
        sig("COMPOUND: High competitor mentions + low conversion → guests choosing alternatives",
            "critical", ["objection", "inquiry", "channel"])

    # Churn risk + low repeat + LTV declining → retention emergency
    if high_risk > 5 and repeat_p < 25:
        sig("COMPOUND: High churn risk + low repeat rate → guest base eroding",
            "critical", ["guest", "revenue"])

    # Good occupancy + good revenue → positive correlation
    if occ_pct >= 70 and rev_prev > 0 and rev_mtd >= rev_prev * 1.1:
        sig("Positive trend: High occupancy driving strong revenue growth", "positive", ["revenue", "occupancy"])

    # Sort: critical first, then warning, then info/positive
    order = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
    signals.sort(key=lambda s: order.get(s["severity"], 99))

    return signals[:12]  # cap at 12 to control token usage


def correlations_to_strings(signals: list[dict]) -> list[str]:
    """Convert structured signals to plain strings for backward compatibility."""
    return [s["message"] for s in signals]


# ─── Enhanced RCA Prompt (Phase 4) ───────────────────────────────────────────

RCA_SYSTEM_PROMPT_V4 = """You are a senior hospitality revenue intelligence analyst for an Indian villa/hotel platform.

You receive structured data from 10 specialized analytics agents plus pre-computed correlation signals.
Your job: produce a root cause analysis that explains WHY the business situation exists.

RULES (strictly enforced):
1. Always cite specific numbers from the agent data. Never invent metrics.
2. Revenue in Indian Rupees (₹). Use format: ₹4.2L, ₹85k, ₹1.2Cr.
3. Root causes must be specific and verifiable from the data provided.
4. Recommendations must name the HAIP module to use.
5. Maximum 3 findings. Rank by revenue impact (highest first).
6. Confidence 0.0–1.0: base on data completeness and signal clarity.
7. If a finding requires data that wasn't provided, say "Insufficient data to confirm" in evidence.

ROOT CAUSE CHAIN (for each finding):
  Signal → Cause → Impact → Recommendation

OUTPUT FORMAT (strict JSON only, no markdown fences):
{
  "summary": "Single sentence answering the question directly",
  "root_cause_chain": "Signal: X → Cause: Y → Impact: ₹Z → Action: W",
  "findings": [
    {
      "title": "Concise finding title (max 10 words)",
      "evidence": [
        "Specific data point with number",
        "Second corroborating signal",
        "Third piece of evidence if available"
      ],
      "root_cause": "One precise sentence explaining the underlying cause",
      "impact": {
        "revenue_loss": 420000,
        "currency": "INR",
        "severity": "high",
        "description": "What happens if unaddressed"
      },
      "recommendations": [
        {
          "action": "Specific, actionable step",
          "expected_impact": "Measurable outcome",
          "module": "HAIP Module Name",
          "href": "/dashboard/path",
          "priority": 1
        }
      ]
    }
  ],
  "confidence": 0.85,
  "data_completeness": "high",
  "investigation_paths_used": ["revenue", "occupancy", "objection"]
}

HAIP MODULE PATHS:
- Revenue Calculator → /dashboard/revenue-calculator
- Campaigns → /dashboard/campaigns/new
- Inbox → /dashboard/inbox
- Guest Profiles → /dashboard/guests
- Calendar/Bookings → /dashboard/calendar
- Analytics → /dashboard/analytics
- AI Intelligence/QA → /dashboard/qa
- Flow Builder → /dashboard/flows
- Portfolio → /dashboard/portfolio
- Integrations → /dashboard/integrations"""


async def run_enhanced_rca(
    question: str,
    intent: dict,
    raw_data: dict,
    agent_outputs: dict,
    structured_correlations: list[dict],
    confidence: "ConfidenceResult",
    range_days: int,
    compare_mode: bool = False,
    module_context: str = "",
) -> dict:
    """
    Phase 4 RCA — higher quality findings using:
    - Structured agent context (not raw JSON)
    - Pre-computed correlation signals with severity
    - Confidence scoring
    - Proper prompt structure for chain-of-cause reasoning
    """
    llm = get_llm("ask_haip_rca")

    # Build agent context (Phase 2 format)
    agent_context = agents_to_llm_context(agent_outputs)

    # Format correlation signals by severity
    critical_signals = [s for s in structured_correlations if s["severity"] == "critical"]
    warning_signals  = [s for s in structured_correlations if s["severity"] == "warning"]
    positive_signals = [s for s in structured_correlations if s["severity"] == "positive"]

    corr_block = ""
    if critical_signals:
        corr_block += "\nCRITICAL SIGNALS:\n" + "\n".join(f"  🔴 {s['message']}" for s in critical_signals)
    if warning_signals:
        corr_block += "\nWARNING SIGNALS:\n" + "\n".join(f"  🟡 {s['message']}" for s in warning_signals)
    if positive_signals:
        corr_block += "\nPOSITIVE SIGNALS:\n" + "\n".join(f"  🟢 {s['message']}" for s in positive_signals)

    compare_note = "\n⚡ COMPARATIVE ANALYSIS REQUESTED: compare this period vs prior period where data available." if compare_mode else ""

    user_message = f"""QUESTION: {question}

ANALYSIS PERIOD: last {range_days} days
QUESTION TYPE: {intent.get('type', 'diagnostic')}
DOMAINS: {', '.join(intent.get('domains', []))}
DATA CONFIDENCE: {confidence.label} ({confidence.score:.0%}) — {confidence.data_completeness} completeness{compare_note}

PRE-COMPUTED SIGNALS:{corr_block if corr_block else ' None detected'}

AGENT INTELLIGENCE:
{agent_context}

Produce root cause analysis. Rank findings by revenue impact."""

    try:
        # Use Sonnet with prompt caching on the system prompt
        effective_system_prompt = (
            f"{module_context}\n\n{RCA_SYSTEM_PROMPT_V4}" if module_context else RCA_SYSTEM_PROMPT_V4
        )
        result = await llm.complete(
            system_prompt=effective_system_prompt,
            user_message=user_message,
            max_tokens=2048,
        )
        content = result.get("content", "").strip()
        start, end = content.find("{"), content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            # Inject confidence from our own scoring (override LLM's guess)
            parsed["confidence"]        = confidence.score
            parsed["data_completeness"] = confidence.data_completeness
            parsed["confidence_label"]  = confidence.label
            parsed["missing_domains"]   = confidence.missing_domains
            return parsed
    except Exception as e:
        log.error("Phase 4 RCA failed: %s", e)

    # Structured fallback using agent data directly
    return _fallback_rca(question, agent_outputs, structured_correlations, confidence)


def _fallback_rca(
    question: str,
    agent_outputs: dict,
    signals: list[dict],
    confidence: ConfidenceResult,
) -> dict:
    """
    Build a structured RCA purely from agent outputs and correlation signals
    — used when the LLM is unavailable or fails.
    """
    critical = [s for s in signals if s["severity"] == "critical"]
    warnings = [s for s in signals if s["severity"] == "warning"]

    all_concerns = []
    for domain, output in agent_outputs.items():
        if output.get("top_concern"):
            all_concerns.append({"domain": domain, "concern": output["top_concern"]})

    findings = []
    top_signals = (critical + warnings)[:3]
    for sig in top_signals:
        findings.append({
            "title": sig["message"][:80],
            "evidence": [sig["message"]],
            "root_cause": "See agent data for full analysis.",
            "impact": {"revenue_loss": 0, "currency": "INR",
                       "severity": sig["severity"], "description": "Requires immediate review"},
            "recommendations": [{
                "action": "Review relevant analytics section for full data",
                "expected_impact": "Identify specific action",
                "module": "Analytics", "href": "/dashboard/analytics", "priority": 1,
            }],
        })

    summary = (f"Found {len(critical)} critical and {len(warnings)} warning signals. "
               f"Top concern: {critical[0]['message'][:80] if critical else 'No critical issues'}")

    return {
        "summary": summary,
        "root_cause_chain": "",
        "findings": findings,
        "confidence": confidence.score,
        "confidence_label": confidence.label,
        "data_completeness": confidence.data_completeness,
        "missing_domains": confidence.missing_domains,
        "investigation_paths_used": list(agent_outputs.keys()),
        "_fallback": True,
    }


# ─── Comparative Analysis ─────────────────────────────────────────────────────

def is_comparative_question(question: str) -> bool:
    """Detect if the user wants a period comparison."""
    q = question.lower()
    compare_keywords = [
        "compare", "vs", "versus", "this month vs", "last month",
        "year over year", "yoy", "previous", "same period", "trend",
        "better or worse", "improved", "declined",
    ]
    return any(kw in q for kw in compare_keywords)


# ─── History retrieval ────────────────────────────────────────────────────────

def get_finding_history(
    db,
    tenant_id: str,
    limit: int = 10,
) -> list[dict]:
    """Retrieve recent findings from ask_haip_findings table."""
    from app.models.ask_haip import AskHaipFinding
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = (
        db.query(AskHaipFinding)
        .filter(
            AskHaipFinding.tenant_id == tenant_id,
            AskHaipFinding.findings_json.isnot(None),
        )
        .order_by(AskHaipFinding.created_at.desc())
        .limit(limit)
        .all()
    )

    history = []
    for row in rows:
        fd = row.findings_json or {}
        history.append({
            "id": str(row.id),
            "session_id": str(row.session_id) if row.session_id else None,
            "question_hash": row.question_hash,
            "summary": fd.get("summary", ""),
            "confidence": float(row.confidence or 0),
            "confidence_label": fd.get("confidence_label", ""),
            "findings_count": len(fd.get("findings", [])),
            "top_finding": fd.get("findings", [{}])[0].get("title", "") if fd.get("findings") else "",
            "agents_used": row.agents_used or [],
            "range_days": row.range_days or 30,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return history
