"""The knowledge "test box": what the AI would be given for a question, from the SAME code paths a real reply uses.

  descriptive text  -> knowledge_service.search_detailed   (also called by concierge_service.build_concierge_context)
  exact data        -> sales_gateway.concierge_business_facts (also called by the concierge task)

Nothing here re-implements retrieval, matching or pricing, so a result here cannot differ from a reply for any reason other than the
language model's own wording. It reads published data only (a draft is never previewed: that would show something the AI cannot use).
It shows where every fact came from (record kind / key / version, or the knowledge entry) and flags what is missing or contradictory.

Flag severities: "info" (good to know), "warn" (the AI will hand over to the team or the answer may be incomplete), "block" (the AI
cannot answer this from the data it has and will say the team will confirm).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.services import knowledge_service, price_policy, sales_gateway
from app.services.business_data_service import list_effective, parse, tenant_today

_STRUCTURED_FLAG_TEXT = {
    "none_published": "No packages are published.",
    "no_package_matches": "No published package matches.",
    "not_published": "That record is not published.",
}


def _flag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


def _human(flag: str) -> str:
    if flag.startswith("destination_not_published:"):
        return f"Destination '{flag.split(':', 1)[1]}' is referenced but not published."
    if flag.startswith("package_not_published:"):
        return f"Package '{flag.split(':', 1)[1]}' is referenced but not published."
    if flag.startswith("itinerary_nights_outside_package_range:"):
        return f"The itinerary's length does not fit package '{flag.split(':', 1)[1]}' (minimum/maximum nights)."
    if flag.startswith("policy_unconfirmed:"):
        return f"{flag.split(':', 1)[1].replace('_', ' ').capitalize()} is published but not confirmed by Ratha, so the AI will not state it."
    if " " in flag:                                  # already a sentence (a quote warning)
        return flag if flag.endswith(".") else flag + "."
    return _STRUCTURED_FLAG_TEXT.get(flag, flag.replace("_", " ").capitalize() + ".")


def _published_amounts(db: Session, tenant_id: str) -> set[int]:
    """Every whole-rupee amount in a published package (rates, extra charges): what a knowledge passage's figure is compared with."""
    out: set[int] = set()
    for rec in list_effective(db, tenant_id, "package"):
        pkg = parse(rec)
        values = [r.amount for r in pkg.rates] + [c.amount for c in pkg.charges]
        if pkg.extra_guest_charge:
            values.append(pkg.extra_guest_charge.amount)
        if pkg.extra_km_charge:
            k = pkg.extra_km_charge
            values += [k.per_km, k.max_per_km, k.min_per_km] + [st.per_km for st in k.ladder]
        if pkg.extra_hour_charge:
            values.append(pkg.extra_hour_charge.per_hour)
        out |= {int(v) for v in values if v is not None}
    return out


def run(db: Session, tenant_id: str, question: str, property_id: Optional[str] = None, details: Optional[dict] = None, top_k: int = 5) -> dict:
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    mode = price_policy.price_mode(tenant)
    flags: list[dict] = []

    # 1) descriptive knowledge -- the reply path's retrieval, unchanged.
    outcome = knowledge_service.search_detailed(db, tenant_id, question, property_id=property_id, top_k=top_k)
    health = knowledge_service.index_health(db, tenant_id)
    if outcome.status == "no_match":
        flags.append(_flag("kb_no_match", "warn", "Nothing in the active, indexed knowledge matches this question."))
    elif outcome.status != "ok":
        flags.append(_flag(f"kb_{outcome.status}", "block", f"Knowledge search status: {outcome.status.replace('_', ' ')}. The AI would answer without it."))
    if health["embedding_pending"] or health["embedding_failed"]:
        flags.append(_flag("kb_index_incomplete", "warn", f"{health['embedding_pending']} entr(ies) waiting and {health['embedding_failed']} failed to index; they cannot be found yet."))

    # 2) exact data -- the concierge's structured facts, unchanged.
    details = {k: v for k, v in (details or {}).items() if v not in (None, "", [])}
    facts = sales_gateway.concierge_business_facts(db, tenant_id, details)
    by_tool = {f["tool"]: f for f in facts}
    sources: list[dict] = []
    structured_flags: list[str] = []
    for f in facts:
        for s in f.get("sources", []):
            ref = {"kind": s["kind"], "key": s["key"], "version": s["version"]}
            if ref not in sources:
                sources.append(ref)
        structured_flags += [x for x in f.get("flags", []) if x not in structured_flags]
    if not facts:
        flags.append(_flag("no_business_data", "warn", "No packages, routes or policies are published, so the AI has no exact data and will say the team will confirm."))
    for code in structured_flags:
        sev = "block" if code.startswith("refused:") else "warn"
        flags.append(_flag(code, sev, _human(code)))

    matched = sales_gateway.match_package(db, tenant_id, details) if by_tool else None
    quote = by_tool.get("package_quote")
    if by_tool and matched is None and (details.get("destination") or details.get("property_hint")):
        flags.append(_flag("package_not_identified", "info", "The destination/package mentioned does not point to exactly one published package, so no quote is attempted."))
    if matched and quote is None:
        missing = [n for n, ok in (("dates", details.get("check_in") and details.get("check_out")), ("number of guests", details.get("adults"))) if not ok]
        flags.append(_flag("quote_needs_details", "info", f"A package is identified; a price needs the {' and '.join(missing)}."))
    if quote is not None and quote["result"].get("refused"):
        flags.append(_flag(f"quote_refused:{quote['result']['refused']}", "block", f"No price can be given: {quote['result'].get('message', '')}"))

    # 3) contradictions between prose and exact data.
    if by_tool:
        published = _published_amounts(db, tenant_id)
        for h in outcome.hits:
            figures = price_policy.money_figures(h["content"])
            if figures:
                stale = [n for n in figures if n not in published]
                flags.append(_flag(
                    "kb_price_in_text", "warn",
                    f"Knowledge passage {h['id'][:8]} states {sorted(set(figures))}. The AI never sees prices in passages (they are removed); "
                    + (f"{sorted(set(stale))} do not match any published rate. Update or remove it." if stale else "they match a published rate."),
                ))

    if mode == "handoff":
        flags.append(_flag("price_mode_handoff", "info", "This workspace is in hand-off mode: the AI never states a price, even when one is available here."))

    return {
        "query": question,
        "price_mode": mode,
        "kb": {"status": outcome.status, "retrievable_count": health["retrievable"], "hits": outcome.hits},
        "structured": {
            "matched_package": matched,
            "sources": sources,
            "descriptive": (by_tool.get("business_data") or {}).get("result"),
            "quote": (quote or {}).get("result"),
            "quote_sources": (quote or {}).get("sources", []),
        },
        "flags": flags,
        "details_used": details,
        "ai_sees_prices": mode == "grounded",
        "as_of": tenant_today(db, tenant_id).isoformat(),
    }
