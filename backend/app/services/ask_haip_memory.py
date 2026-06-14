"""
Ask HAIP — Phase 6: Conversation Memory

Enables multi-turn intelligence:
  "Why did revenue drop?" → "Now show me only Villa Serenity" → "Compare to last month"

Memory is stored in Redis (TTL 2h) keyed by (tenant_id, session_id).
Falls back to no-memory mode if Redis is unavailable.

Memory object:
  - previous_questions: last 5 questions
  - last_domains: domains from last analysis
  - last_findings: top finding from last RCA
  - context_vars: property_ids, range_days, date filters extracted from conversation
  - last_result_summary: 1-sentence summary of last answer
"""

from __future__ import annotations

import json
import re
import logging
from typing import Optional

from app.core.cache import get_cached, set_cached, cache_key

log = logging.getLogger(__name__)

MEMORY_TTL = 7200   # 2 hours


def _memory_key(tenant_id: str, session_id: str) -> str:
    return cache_key("ask_memory", tenant_id, sid=session_id)


def load_memory(tenant_id: str, session_id: str) -> dict:
    """Load conversation memory for this session."""
    ck = _memory_key(tenant_id, session_id)
    return get_cached(ck) or _empty_memory()


def save_memory(tenant_id: str, session_id: str, memory: dict) -> None:
    """Persist updated memory."""
    ck = _memory_key(tenant_id, session_id)
    set_cached(ck, memory, ttl=MEMORY_TTL)


def _empty_memory() -> dict:
    return {
        "previous_questions": [],
        "last_domains": [],
        "last_findings": [],
        "context_vars": {
            "property_ids": None,
            "range_days": 30,
            "property_name": None,
        },
        "last_result_summary": "",
    }


def update_memory(
    memory: dict,
    question: str,
    result: dict,
) -> dict:
    """Update memory with the latest question and result."""
    # Keep last 5 questions
    questions = memory.get("previous_questions", [])
    questions.append(question)
    memory["previous_questions"] = questions[-5:]

    # Store context from result
    memory["last_domains"]        = result.get("intent", {}).get("domains", [])
    memory["last_result_summary"] = result.get("summary", "")

    # Store top finding
    findings = result.get("findings", [])
    memory["last_findings"] = [f.get("title", "") for f in findings[:2]]

    return memory


def resolve_context(question: str, memory: dict) -> dict:
    """
    Parse the new question against memory context to resolve:
    - Property references ("that property", "Villa Serenity", "the one with low occupancy")
    - Time references ("last month", "same period last year", "this year")
    - Comparative intent ("compare", "vs", "difference")

    Returns updated context_vars.
    """
    ctx = dict(memory.get("context_vars", {}))
    q   = question.lower()

    # Property resolution — explicit name
    prop_match = re.search(
        r"(?:for|at|show me|only|filter|villa|property)\s+([A-Z][a-zA-Z\s]{2,30}?)(?:\s|$|,|\?)",
        question
    )
    if prop_match:
        ctx["property_name"] = prop_match.group(1).strip()

    # Range resolution
    if "last week" in q or "7 days" in q:
        ctx["range_days"] = 7
    elif "last month" in q or "30 days" in q:
        ctx["range_days"] = 30
    elif "last quarter" in q or "90 days" in q or "3 months" in q:
        ctx["range_days"] = 90
    elif "this year" in q or "ytd" in q or "year to date" in q:
        ctx["range_days"] = 365

    # Comparative intent
    ctx["compare_mode"] = any(w in q for w in [
        "compare", "vs", "versus", "difference", "better", "worse",
        "last month", "previous", "year over year", "yoy",
    ])

    return ctx


def build_context_note(memory: dict, question: str) -> str:
    """
    Build a short context note to inject into the LLM prompt
    so it knows about the conversation history.
    """
    parts = []

    prev = memory.get("previous_questions", [])
    if prev:
        parts.append(f"Previous questions: {' | '.join(prev[-3:])}")

    summary = memory.get("last_result_summary", "")
    if summary:
        parts.append(f"Last analysis: {summary}")

    findings = memory.get("last_findings", [])
    if findings:
        parts.append(f"Previous findings: {'; '.join(findings)}")

    ctx = memory.get("context_vars", {})
    if ctx.get("property_name"):
        parts.append(f"Active property filter: {ctx['property_name']}")

    if not parts:
        return ""
    return "CONVERSATION CONTEXT:\n" + "\n".join(parts)


def generate_suggestions(result: dict, memory: dict) -> list[dict]:
    """
    Phase 6: Generate 3 proactive follow-up suggestions based on the analysis result.

    Logic:
    1. If critical signal found → suggest drilling into that domain
    2. If domains not yet explored → suggest exploring them
    3. Context-aware: if revenue dropped → suggest objection analysis
    """
    suggestions = []
    signals     = result.get("structured_signals", [])
    domains_run = set(result.get("investigation_paths_used", []))
    findings    = result.get("findings", [])

    # 1. Finding-based suggestions
    if findings:
        top = findings[0]
        title_lower = top.get("title", "").lower()

        if "revenue" in title_lower:
            suggestions.append({
                "question": "What objections are causing revenue loss?",
                "reason": "Revenue finding detected — objection analysis recommended",
                "icon": "⚠️",
            })
        if "occupancy" in title_lower:
            suggestions.append({
                "question": "Which properties have the lowest occupancy?",
                "reason": "Occupancy finding — property drill-down recommended",
                "icon": "🏠",
            })
        if "churn" in title_lower or "guest" in title_lower:
            suggestions.append({
                "question": "Which guests are at highest churn risk?",
                "reason": "Guest retention signal detected",
                "icon": "👥",
            })

    # 2. Signal-based suggestions
    critical = [s for s in signals if s.get("severity") == "critical"]
    for sig in critical[:2]:
        domains = sig.get("domains", [])
        if "channel" in domains and "channel" not in domains_run:
            suggestions.append({
                "question": "Why is WhatsApp delivery rate low?",
                "reason": "Channel health signal detected",
                "icon": "📡",
            })
        if "objection" in domains and "objection" not in domains_run:
            suggestions.append({
                "question": "What objections are increasing this month?",
                "reason": "Objection signal not yet investigated",
                "icon": "💬",
            })

    # 3. Unexplored domain suggestions
    all_domains = ["revenue", "occupancy", "inquiry", "guest", "channel", "objection", "intent", "property"]
    unexplored  = [d for d in all_domains if d not in domains_run][:2]
    domain_questions = {
        "revenue":   ("What is the revenue forecast for next month?", "📈"),
        "occupancy": ("Which properties are forecasting low occupancy?", "🏠"),
        "inquiry":   ("Where is the inquiry funnel leaking?", "🔍"),
        "guest":     ("Which guests generate the highest lifetime value?", "⭐"),
        "channel":   ("Which channel converts best this month?", "📡"),
        "objection": ("Which objections are costing the most revenue?", "⚠️"),
        "intent":    ("Which travel intent converts best?", "🎯"),
        "property":  ("Which property is underperforming vs portfolio?", "🏠"),
    }
    for d in unexplored:
        if d in domain_questions:
            q, icon = domain_questions[d]
            suggestions.append({"question": q, "reason": f"{d} not yet analyzed", "icon": icon})

    # Deduplicate and limit to 3
    seen = set()
    unique = []
    for s in suggestions:
        if s["question"] not in seen:
            seen.add(s["question"])
            unique.append(s)
    return unique[:3]
