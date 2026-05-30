"""
Ask HAIP Service — Hospitality Intelligence Analyst

Layers:
  1. Intent Detection    — classify question → domains + type (Haiku)
  2. Agent Runner        — call relevant analytics endpoints, return structured data
  3. Path Generator      — build ThinkPath investigation paths
  4. Root Cause Engine   — synthesize agent data → findings (Sonnet)

All analytics data comes from EXISTING endpoints via internal HTTP or direct
service function calls — no new SQL queries in this file.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.adapters.llm import get_llm_adapter
from app.core.cache import cache_key, get_cached, set_cached
from app.models.ask_haip import AskHaipSession, AskHaipFinding
from app.models.base import gen_uuid
from app.services.ask_haip_agents import process_agents, agents_to_llm_context
from app.services.ask_haip_rca import (
    build_correlations, correlations_to_strings,
    calculate_confidence, run_enhanced_rca, is_comparative_question,
)

log = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────

DOMAINS = [
    "revenue", "occupancy", "inquiry", "guest",
    "channel", "campaign", "property", "objection",
    "intent", "attribution",
]

QUESTION_TYPES = ["diagnostic", "comparative", "predictive", "descriptive"]

# Domain → analytics endpoint mapping
DOMAIN_ENDPOINTS: dict[str, list[str]] = {
    "revenue":     ["/analytics/executive", "/analytics/properties", "/analytics/forecasting/revenue"],
    "occupancy":   ["/analytics/executive", "/analytics/forecasting/occupancy", "/analytics/properties"],
    "inquiry":     ["/analytics/executive", "/analytics/owner-daily", "/analytics/lost-reasons"],
    "guest":       ["/analytics/guests", "/analytics/forecasting/churn", "/analytics/forecasting/cohorts"],
    "channel":     ["/analytics/channels", "/analytics/attribution"],
    "campaign":    ["/analytics/campaigns"],
    "property":    ["/analytics/properties", "/analytics/forecasting/pricing"],
    "objection":   ["/analytics/objections"],
    "intent":      ["/analytics/intent"],
    "attribution": ["/analytics/attribution"],
}

# Path library: domain → template
PATH_LIBRARY: dict[str, dict] = {
    "revenue": {
        "name": "Revenue Investigation",
        "icon": "₹",
        "domains": ["revenue", "occupancy"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Revenue MTD vs prior period, daily trend"},
            {"step": 2, "label": "Diagnose", "description": "Which properties/channels lost the most?"},
            {"step": 3, "label": "Recommend", "description": "Pricing adjustments, follow-up actions"},
        ],
    },
    "inquiry": {
        "name": "Inquiry Funnel",
        "icon": "🔍",
        "domains": ["inquiry", "channel"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Inquiry volume, stage distribution, conversion funnel"},
            {"step": 2, "label": "Diagnose", "description": "Where in the funnel are leads leaking?"},
            {"step": 3, "label": "Recommend", "description": "SLA improvements, response rate fixes"},
        ],
    },
    "channel": {
        "name": "Channel Performance",
        "icon": "📡",
        "domains": ["channel", "attribution"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Channel mix, delivery rates, response times"},
            {"step": 2, "label": "Diagnose", "description": "Which channel dropped? Attribution shift?"},
            {"step": 3, "label": "Recommend", "description": "Channel rebalancing, campaign actions"},
        ],
    },
    "objection": {
        "name": "Objection Analysis",
        "icon": "⚠️",
        "domains": ["objection", "inquiry"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Objection frequency over time (Pareto)"},
            {"step": 2, "label": "Diagnose", "description": "Budget objections spiking? Competition rising?"},
            {"step": 3, "label": "Recommend", "description": "Pricing strategy, offer adjustments"},
        ],
    },
    "guest": {
        "name": "Guest Intelligence",
        "icon": "👥",
        "domains": ["guest"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Repeat guest rate, new vs returning, LTV trend"},
            {"step": 2, "label": "Diagnose", "description": "Churn risk? VIP segment shrinking?"},
            {"step": 3, "label": "Recommend", "description": "Retention campaigns, win-back sequences"},
        ],
    },
    "property": {
        "name": "Property Performance",
        "icon": "🏠",
        "domains": ["property", "occupancy"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "RevPAR matrix across properties"},
            {"step": 2, "label": "Diagnose", "description": "Which property underperforms and why?"},
            {"step": 3, "label": "Recommend", "description": "Pricing audit, blocking review"},
        ],
    },
    "intent": {
        "name": "Intent Analysis",
        "icon": "🎯",
        "domains": ["intent"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Travel intent distribution and trend"},
            {"step": 2, "label": "Diagnose", "description": "Which intent converts best? Which is declining?"},
            {"step": 3, "label": "Recommend", "description": "Targeting adjustment, content strategy"},
        ],
    },
    "campaign": {
        "name": "Campaign ROI",
        "icon": "📢",
        "domains": ["campaign"],
        "steps": [
            {"step": 1, "label": "Analyze", "description": "Campaign delivery, read rates, conversions"},
            {"step": 2, "label": "Diagnose", "description": "Which template performs best/worst?"},
            {"step": 3, "label": "Recommend", "description": "Campaign optimization, template refresh"},
        ],
    },
}

# Correlation rules: (domain_a, domain_b) → signal label
CORRELATION_RULES = [
    ({"occupancy"}, {"objection"},  "Price sensitivity signal — occupancy falling while objections rise"),
    ({"inquiry"},   {"channel"},    "Channel health issue — inquiry drop may be delivery/response related"),
    ({"revenue"},   {"intent"},     "Guest segment mismatch — revenue shift may follow intent trend change"),
    ({"guest"},     {"revenue"},    "Retention risk — churn pressure likely impacting revenue"),
    ({"objection"}, {"attribution"},"Competitive pressure — objections may be channel or source specific"),
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _question_hash(question: str, range_days: int, property_ids: Optional[list]) -> str:
    key = f"{question.strip().lower()}|{range_days}|{sorted(property_ids or [])}"
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Layer 1: Intent Detection ────────────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """You are a question classifier for a hospitality analytics platform.

Given a question from a hotel/villa operator, return a JSON object:
{
  "domains": ["domain1", "domain2"],   // 1-4 from the allowed list
  "type": "diagnostic",               // one of: diagnostic | comparative | predictive | descriptive
  "time_range": "last_30_days",       // last_7_days | last_30_days | last_90_days | month_to_date | year_to_date
  "entities": {}                      // any property names, channels, or dates mentioned
}

Allowed domains: revenue, occupancy, inquiry, guest, channel, campaign, property, objection, intent, attribution

Rules:
- "Why" questions → diagnostic
- "Which is best/worst" → comparative
- "What will happen / forecast" → predictive
- "Show me / What is" → descriptive
- Revenue questions → always include revenue + at least one of: occupancy, inquiry
- Booking questions → inquiry + channel + attribution
- Guest questions → guest (+ revenue if LTV mentioned)
- Property questions → property + occupancy

Return ONLY valid JSON, no explanation."""


async def detect_intent(question: str) -> dict:
    """Use Claude Haiku to classify the question into domains + type."""
    llm = get_llm_adapter()
    try:
        result = await llm.complete(
            system_prompt=INTENT_SYSTEM_PROMPT,
            user_message=question,
            max_tokens=256,
        )
        content = result.get("content", "").strip()
        # Extract JSON from response
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception as e:
        log.warning("Intent detection failed, using keyword fallback: %s", e)

    # Keyword fallback
    q = question.lower()
    domains = []
    if any(w in q for w in ["revenue", "money", "income", "earning", "₹", "inr"]):
        domains += ["revenue", "occupancy"]
    if any(w in q for w in ["booking", "inquiry", "lead", "funnel", "conversion"]):
        domains += ["inquiry", "channel"]
    if any(w in q for w in ["occupancy", "vacant", "available", "empty"]):
        domains += ["occupancy", "property"]
    if any(w in q for w in ["guest", "repeat", "churn", "ltv", "retention"]):
        domains += ["guest"]
    if any(w in q for w in ["channel", "whatsapp", "instagram", "email"]):
        domains += ["channel", "attribution"]
    if any(w in q for w in ["objection", "budget", "competition", "lost", "reason"]):
        domains += ["objection", "inquiry"]
    if any(w in q for w in ["intent", "honeymoon", "occasion", "travel"]):
        domains += ["intent"]
    if any(w in q for w in ["campaign", "template", "blast", "broadcast"]):
        domains += ["campaign"]
    if any(w in q for w in ["property", "villa", "underperform", "perform"]):
        domains += ["property", "occupancy"]
    if any(w in q for w in ["attribution", "source", "first touch", "where from"]):
        domains += ["attribution", "channel"]

    if not domains:
        domains = ["revenue", "inquiry"]  # safe default

    q_type = "diagnostic" if any(w in q for w in ["why", "reason", "cause", "problem"]) else \
             "comparative" if any(w in q for w in ["best", "worst", "compare", "vs", "which"]) else \
             "predictive" if any(w in q for w in ["forecast", "predict", "will", "next"]) else \
             "descriptive"

    return {
        "domains": list(dict.fromkeys(domains)),  # deduplicate preserving order
        "type": q_type,
        "time_range": "last_30_days",
        "entities": {},
    }


# ─── Layer 2: Agent Data Fetching ─────────────────────────────────────────────

async def _fetch_analytics(endpoint: str, token: str, base_url: str,
                           range_days: int, property_ids: Optional[list]) -> Optional[dict]:
    """Fetch data from an existing analytics endpoint."""
    import httpx
    params: dict = {"range_days": range_days}
    if property_ids:
        params["property_ids"] = ",".join(property_ids)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{base_url}{endpoint}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.warning("Agent fetch failed for %s: %s", endpoint, e)
    return None


async def run_agents(
    domains: list[str],
    token: str,
    base_url: str,
    range_days: int = 30,
    property_ids: Optional[list] = None,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """
    Phase 2: Run all agents for detected domains.

    Returns:
      raw_data    — dict[endpoint_path → raw API response]
      agent_outputs — dict[domain → structured AgentOutput]
    """
    import asyncio

    endpoints_to_fetch: set[str] = set()
    for domain in domains:
        for ep in DOMAIN_ENDPOINTS.get(domain, []):
            endpoints_to_fetch.add(ep)

    tasks = {
        ep: _fetch_analytics(ep, token, base_url, range_days, property_ids)
        for ep in endpoints_to_fetch
    }

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    raw_data = {
        ep: (r if not isinstance(r, Exception) else None)
        for ep, r in zip(tasks.keys(), results)
    }

    # Run structured agent processors (pure functions, no I/O)
    agent_outputs = process_agents(domains, raw_data)

    return raw_data, agent_outputs


# ─── Layer 3: Path Generator ──────────────────────────────────────────────────

def generate_paths(domains: list[str], agent_data: dict) -> list[dict]:
    """
    Generate 2-5 investigation paths from the detected domains.
    Each path uses PATH_LIBRARY templates, enriched with live metric snapshot.
    """
    paths = []
    seen_domains: set[str] = set()

    for domain in domains:
        if domain in PATH_LIBRARY and domain not in seen_domains:
            template = PATH_LIBRARY[domain]
            path = {
                "id": domain,
                "name": template["name"],
                "icon": template["icon"],
                "domains": template["domains"],
                "steps": [dict(s, status="pending", data=None) for s in template["steps"]],
                "snapshot": _extract_snapshot(domain, agent_data),
            }
            paths.append(path)
            for d in template["domains"]:
                seen_domains.add(d)

    return paths[:5]


def _extract_snapshot(domain: str, agent_data: dict) -> dict:
    """Extract a brief KPI snapshot for the path header."""
    snap: dict = {}
    try:
        if domain == "revenue":
            exec_data = agent_data.get("/analytics/executive", {}) or {}
            snap["revenue_mtd"] = exec_data.get("revenue_mtd", 0)
            snap["occupancy_pct"] = exec_data.get("occupancy_pct", 0)
        elif domain == "inquiry":
            exec_data = agent_data.get("/analytics/executive", {}) or {}
            snap["active_inquiries"] = exec_data.get("active_inquiries", 0)
        elif domain == "objection":
            obj_data = agent_data.get("/analytics/objections", {}) or {}
            snap["top_objection"] = obj_data.get("top_objection")
            snap["total_revenue_lost"] = obj_data.get("total_revenue_lost", 0)
        elif domain == "guest":
            g_data = agent_data.get("/analytics/guests", {}) or {}
            snap["total_guests"] = g_data.get("total_guests", 0)
            snap["repeat_pct"] = g_data.get("repeat_pct", 0)
        elif domain == "channel":
            ch_data = agent_data.get("/analytics/channels", {}) or {}
            snap["delivery_rate_pct"] = ch_data.get("delivery_rate_pct", 0)
        elif domain == "intent":
            int_data = agent_data.get("/analytics/intent", {}) or {}
            snap["top_intent"] = int_data.get("top_intent")
            snap["top_intent_conversion"] = int_data.get("top_intent_conversion", 0)
    except Exception:
        pass
    return snap


# ─── Layer 4: Correlation Engine ─────────────────────────────────────────────

def detect_correlations(domains: list[str], agent_data: dict,
                        agent_outputs: Optional[dict] = None) -> list[str]:
    """
    Apply heuristic correlation rules across agent data.
    Returns list of signal strings to inject into LLM prompt.
    """
    signals = []
    domain_set = set(domains)

    for (set_a, set_b, signal) in CORRELATION_RULES:
        if set_a & domain_set and set_b & domain_set:
            signals.append(signal)

    # Numeric correlation checks
    try:
        exec_d = agent_data.get("/analytics/executive", {}) or {}
        occ = float(exec_d.get("occupancy_pct") or 0)
        if occ < 40:
            signals.append(f"CRITICAL: Portfolio occupancy is very low ({occ}%) — investigate immediately")
        elif occ < 60:
            signals.append(f"WARNING: Occupancy below target ({occ}%)")
    except Exception:
        pass

    try:
        obj_d = agent_data.get("/analytics/objections", {}) or {}
        budget_pct = float(obj_d.get("budget_objection_pct") or 0)
        if budget_pct > 40:
            signals.append(f"HIGH budget objection rate ({budget_pct:.0f}%) — price sensitivity critical")
    except Exception:
        pass

    try:
        churn_d = agent_data.get("/analytics/forecasting/churn", {}) or {}
        high_risk = int(churn_d.get("high_risk_count") or 0)
        rev_at_risk = float(churn_d.get("revenue_at_risk") or 0)
        if high_risk > 5:
            signals.append(f"{high_risk} guests at high churn risk — ₹{rev_at_risk:,.0f} revenue exposure")
    except Exception:
        pass

    return signals


# ─── Layer 5: Root Cause Engine ───────────────────────────────────────────────

RCA_SYSTEM_PROMPT = """You are a senior hospitality intelligence analyst for an Indian villa/hotel platform.

You receive a business question and structured analytics data from 10 specialized agents.
Your job: produce a root cause analysis in strict JSON format.

Rules:
- Always cite specific numbers from the data. Never invent metrics.
- If data is missing for a domain, say so explicitly in evidence.
- Revenue figures in Indian Rupees (₹). Format: ₹4.2L, ₹12k, etc.
- Recommendations must link to specific platform modules.
- Maximum 3 findings. Rank by revenue impact (highest first).
- Confidence: 0.0–1.0 based on data completeness.

Output format (strict JSON, no markdown):
{
  "summary": "One-sentence headline answer to the question",
  "findings": [
    {
      "title": "Short finding title",
      "evidence": ["bullet 1 with specific number", "bullet 2", "bullet 3"],
      "impact": {"revenue_loss": 420000, "currency": "INR", "severity": "high"},
      "root_cause": "One sentence root cause",
      "recommendations": [
        {
          "action": "Specific action",
          "expected_impact": "Estimated outcome",
          "module": "Module name",
          "href": "/dashboard/module-path"
        }
      ]
    }
  ],
  "confidence": 0.85,
  "data_completeness": "high",
  "investigation_paths_used": ["revenue", "occupancy"]
}

Module paths:
- Revenue Calculator: /dashboard/revenue-calculator
- Campaigns: /dashboard/campaigns/new
- Inbox: /dashboard/inbox
- Guests: /dashboard/guests
- Properties/Calendar: /dashboard/calendar
- Analytics: /dashboard/analytics
- Flow Builder: /dashboard/flows"""


async def run_rca(
    question: str,
    intent: dict,
    agent_data: dict,
    correlations: list[str],
    range_days: int,
    agent_outputs: Optional[dict] = None,
) -> dict:
    """
    Synthesize all agent data into a structured root cause analysis.
    Phase 2: Uses structured AgentOutput context for higher quality findings.
    Uses Claude Sonnet (most capable) for quality findings.
    """
    llm = get_llm_adapter()

    # Phase 2: Use structured agent context if available, fall back to raw data summary
    if agent_outputs:
        data_summary = agents_to_llm_context(agent_outputs)
    else:
        data_summary = _summarize_agent_data(agent_data)

    correlation_block = ""
    if correlations:
        correlation_block = "\n\nHYPOTHESES TO INVESTIGATE:\n" + "\n".join(f"- {s}" for s in correlations)

    user_message = f"""Question: {question}

Period: last {range_days} days
Question type: {intent.get('type', 'diagnostic')}
Domains: {', '.join(intent.get('domains', []))}
{correlation_block}

Analytics Data:
{data_summary}

Provide root cause analysis."""

    try:
        from app.adapters.llm.anthropic_claude import MODEL_SONNET
        result = await llm.complete(
            system_prompt=RCA_SYSTEM_PROMPT,
            user_message=user_message,
            model=MODEL_SONNET,
            max_tokens=2048,
        )
        content = result.get("content", "").strip()
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception as e:
        log.error("RCA synthesis failed: %s", e)

    # Graceful fallback
    return {
        "summary": "Analysis complete — see findings below.",
        "findings": [],
        "confidence": 0.3,
        "data_completeness": "partial",
        "investigation_paths_used": intent.get("domains", []),
        "error": "LLM synthesis unavailable — check API key configuration",
    }


def _summarize_agent_data(agent_data: dict) -> str:
    """Convert agent data dict into a concise, numbered summary for the LLM prompt."""
    lines = []
    for ep, data in agent_data.items():
        if not data:
            lines.append(f"[{ep}]: No data available")
            continue
        # Trim to avoid token bloat — keep top-level fields only
        if isinstance(data, dict):
            trimmed = {k: v for k, v in data.items() if not isinstance(v, list) or len(str(v)) < 300}
            lines.append(f"[{ep}]: {json.dumps(trimmed, default=str)[:800]}")
        else:
            lines.append(f"[{ep}]: {str(data)[:200]}")
    return "\n".join(lines)


# ─── Main Entry Point ─────────────────────────────────────────────────────────

async def ask_haip(
    question: str,
    tenant_id: str,
    user_id: str,
    token: str,
    base_url: str,
    range_days: int = 30,
    property_ids: Optional[list] = None,
    db: Optional[Session] = None,
) -> dict:
    """
    Full Ask HAIP pipeline:
      1. Check finding cache (Redis + DB)
      2. Detect intent
      3. Run agents
      4. Generate paths
      5. Detect correlations
      6. Run RCA
      7. Persist session + finding
      8. Return structured response
    """
    q_hash = _question_hash(question, range_days, property_ids)

    # Cache check
    ck = cache_key("ask_haip", tenant_id, hash=q_hash)
    if (cached := get_cached(ck)) is not None:
        return cached

    # 1. Intent detection
    intent = await detect_intent(question)

    # 2. Run agents in parallel (Phase 2: returns raw_data + structured agent_outputs)
    raw_data, agent_outputs = await run_agents(
        domains=intent.get("domains", ["revenue"]),
        token=token,
        base_url=base_url,
        range_days=range_days,
        property_ids=property_ids,
    )

    # 3. Generate investigation paths (enriched with agent snapshot data)
    paths = generate_paths(intent.get("domains", []), raw_data)

    # 4. Phase 4: Enhanced correlation engine (20+ rules, structured signals)
    domains = intent.get("domains", [])
    structured_signals = build_correlations(domains, raw_data, agent_outputs)
    correlations = correlations_to_strings(structured_signals)

    # Phase 4: Confidence scoring
    confidence = calculate_confidence(domains, agent_outputs, correlations)

    # Phase 4: Detect comparative question
    compare_mode = is_comparative_question(question)

    # 5. Phase 4: Enhanced Root Cause Engine (20+ correlations + confidence + chain)
    rca = await run_enhanced_rca(
        question=question,
        intent=intent,
        raw_data=raw_data,
        agent_outputs=agent_outputs,
        structured_correlations=structured_signals,
        confidence=confidence,
        range_days=range_days,
        compare_mode=compare_mode,
    )

    # 6. Build response — Phase 4 adds confidence detail, signals, root_cause_chain
    session_id = gen_uuid()
    response = {
        "session_id": session_id,
        "question": question,
        "intent": intent,
        "paths": paths,
        "correlations": correlations,
        "structured_signals": structured_signals,   # Phase 4: severity-tagged
        "findings": rca.get("findings", []),
        "summary": rca.get("summary", ""),
        "root_cause_chain": rca.get("root_cause_chain", ""),
        "confidence": float(rca.get("confidence", confidence.score)),
        "confidence_label": confidence.label,
        "data_completeness": rca.get("data_completeness", confidence.data_completeness),
        "missing_domains": confidence.missing_domains,
        "investigation_paths_used": rca.get("investigation_paths_used", domains),
        "compare_mode": compare_mode,
        "agents": agent_outputs,
    }

    # 7. Persist (non-blocking — don't fail if DB is unavailable)
    if db:
        try:
            now = _now()
            session = AskHaipSession(
                id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                question=question,
                intent_json=intent,
                paths_generated=paths,
                range_days=range_days,
                property_ids=property_ids,
            )
            db.add(session)

            finding = AskHaipFinding(
                id=gen_uuid(),
                tenant_id=tenant_id,
                session_id=session_id,
                question_hash=q_hash,
                findings_json=rca,
                agents_used=list(agent_data.keys()),
                range_days=range_days,
                property_ids=property_ids,
                confidence=rca.get("confidence"),
                expires_at=now + timedelta(hours=1),
            )
            db.add(finding)
            db.commit()
        except Exception as e:
            log.warning("Failed to persist Ask HAIP session: %s", e)
            db.rollback()

    # 8. Cache response
    set_cached(ck, response, ttl=3600)  # 1hr
    return response
