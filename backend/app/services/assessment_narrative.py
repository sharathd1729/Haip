"""Optional plain-language write-up of a property assessment (Celery ``assessment.narrative``, never in a request).

The model gets ONLY the facts below, all computed by assessment_engine (no name, phone or email), and may only restate
them. ``check_numbers`` rejects any reply containing a number that is not in the facts, character for character after
dropping thousands separators: "5.4 crore" for "₹5,37,41,372" is rejected, so is any invented figure. A rejected or
failed write-up is simply not shown; the report never depends on it.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog

from app.core.prompt_versions import PROMPT_VERSIONS
from app.services.assessment_engine import _inr

log = structlog.get_logger()

PROMPT_KEY = "assessment_narrative"
TIMEOUT_S = 90
_NUMBER_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")

SYSTEM_PROMPT = (
    "You write a short, plain-English summary (90 to 140 words, 2 short paragraphs) of a hospitality property "
    "projection for the property's owner. Use ONLY the facts given. Copy every number exactly as written in the facts, "
    "including the rupee sign and commas; never round, convert to lakh or crore, add up, or work out any new number. "
    "Do not write any number that is not in the facts. Say these are estimates from sample benchmarks. "
    "No headings, no lists, no advice to invest."
)


def facts(result: dict) -> str:
    y, inv, pay = result["yearly"], result["investment"], result["payback_months"]
    months = result["monthly"]
    busiest = max(months, key=lambda m: m["revenue"]["likely"])["month"]
    quietest = min(months, key=lambda m: m["revenue"]["likely"])["month"]
    lines = [
        f"Property: {result['property_type_label']}, {result['segment_label']}, {result['keys']} rooms, "
        f"plot {result['plot_sqft']:,} sq ft, location type {result['location_label']}.",
        f"Yearly revenue: low {_inr(y['low']['revenue'])}, likely {_inr(y['likely']['revenue'])}, high {_inr(y['high']['revenue'])}.",
        f"Average monthly revenue (likely): {_inr(y['likely']['monthly_average_revenue'])}.",
        f"Average occupancy (likely): {round(y['likely']['average_occupancy'] * 100)}%.",
        f"Busiest month: {busiest}. Quietest month: {quietest}.",
        f"Yearly net operating income (likely): {_inr(y['likely']['net_operating_income'])}.",
        f"Investment estimate: {_inr(inv['total'])}.",
        "Payback (likely): " + (f"{pay['likely']} months." if pay["likely"] else "none, costs exceed revenue."),
        f"Running costs: {round(result['running_cost_pct'] * 100)}% of revenue. OTA share: "
        f"{round(result['ota_share'] * 100)}% of room revenue at {round(result['ota_commission_pct'] * 100)}% commission.",
        f"Benchmarks: version {result['benchmark_version']}" + (" (sample values)." if result.get("benchmark_sample") else "."),
    ]
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER_RE.finditer(text or "")}


def check_numbers(fact_text: str, reply: str) -> Optional[str]:
    """None when every number in the reply appears in the facts, else the reason it is rejected."""
    extra = _numbers(reply) - _numbers(fact_text)
    return f"introduced numbers {sorted(extra)}" if extra else None


async def _complete(fact_text: str) -> str:
    from app.adapters.llm import get_llm
    llm = get_llm(PROMPT_KEY)
    resp = await asyncio.wait_for(
        llm.complete(system_prompt=SYSTEM_PROMPT, user_message=fact_text, max_tokens=500), timeout=TIMEOUT_S)
    return (resp.get("content") or "").strip()


def write(db, lead_id: str) -> dict:
    """Generate, check and store the write-up for one assessment lead. Safe to call twice."""
    from app.models.platform_lead import PlatformLead

    lead = db.query(PlatformLead).filter_by(id=lead_id).first()
    if lead is None or lead.kind != "assessment" or not lead.assessment or lead.narrative_status == "done":
        return {"status": "skipped"}
    fact_text = facts(lead.assessment["result"])
    version = PROMPT_VERSIONS[PROMPT_KEY]
    try:
        reply = asyncio.run(_complete(fact_text))
    except Exception as exc:  # noqa: BLE001 -- provider error or timeout: the report simply has no write-up
        lead.narrative_status = "failed"
        lead.narrative_prompt_version = version
        db.commit()
        log.warning("assessment_narrative_failed", lead_id=lead_id, error=type(exc).__name__, prompt_version=version)
        return {"status": "failed"}
    reason = check_numbers(fact_text, reply) if reply else "empty reply"
    lead.narrative_prompt_version = version
    if reason:
        lead.narrative_status = "rejected"
        db.commit()
        log.warning("assessment_narrative_rejected", lead_id=lead_id, reason=reason, prompt_version=version)
        return {"status": "rejected", "reason": reason}
    lead.narrative = reply[:2000]
    lead.narrative_status = "done"
    db.commit()
    log.info("assessment_narrative_done", lead_id=lead_id, prompt_version=version)
    return {"status": "done"}
