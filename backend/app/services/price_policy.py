"""Price-disclosure policy for the AI concierge.

Business rule (Ratha, 2026-08-20): the AI must NEVER quote pricing in chat.
It collects the lead's details, then a human agent connects personally to
discuss and negotiate. Pricing is a commercial conversation the brand wants
a person to own.

This module is the enforcement half of that rule. The prompt asks the model
not to quote prices; this makes it true regardless of whether the model
complies, because "usually obeys the instruction" is not a policy -- a
single leaked rate sent unreviewed to a guest is exactly the outcome the
rule exists to prevent.

Three responsibilities:
  1. detect_price()  -- catch a price in generated text, broadly.
  2. redact_price_facts() -- strip figures from grounded_facts before they
     are rendered into the prompt, so the model is never shown a number it
     could repeat.
  3. missing_lead_details() -- what still needs collecting before handoff.

Two modes (`tenant.brand_config["price_disclosure"]`, see price_mode()):
  "handoff"  (default, Ratha's rule) -- no price ever appears in chat.
  "grounded" -- the AI may state a price ONLY if it is a figure from the
                live rate/quote lookup for the exact property, dates and party
                (unsupported_figures() is the gate). Anything else is still
                blocked, and with no live figure the reply says the rate needs
                confirming. Never a negotiation either way.
"""

from __future__ import annotations

import json
import re
from typing import Optional

PRICE_MODES = ("handoff", "grounded")


def price_mode(tenant) -> str:
    """How this tenant lets the AI talk about price. Anything unrecognised means the safe default, "handoff"."""
    cfg = getattr(tenant, "brand_config", None) or {}
    value = cfg.get("price_disclosure") if isinstance(cfg, dict) else None
    return value if value in PRICE_MODES else "handoff"

# Deliberately broad. The pre-existing _MONEY_RE in concierge_draft only
# matched a literal "₹" and would miss every one of: "Rs 12,000",
# "INR 12000", "12k per night", "starts at 8000", "around 15,000/-".
_PRICE_PATTERNS = [
    # Currency symbol or code followed by digits
    re.compile(r"(?:₹|\bRs\.?\b|\bINR\b|\bUSD\b|\$|\bEUR\b|€)\s*[\d][\d,]*(?:\.\d+)?(?:\s*k\b)?", re.IGNORECASE),
    # Digits followed by a currency word/suffix
    re.compile(r"\b[\d][\d,]*(?:\.\d+)?\s*(?:₹|\brupees?\b|\bRs\.?\b|\bINR\b|/-)", re.IGNORECASE),
    # Digits attached to a rate unit -- "12000 per night", "8k a day",
    # "15,000/night", "20000 pn"
    re.compile(
        r"\b[\d][\d,]*(?:\.\d+)?\s*k?\s*(?:/|per\s+|a\s+|pp\b|pn\b)\s*"
        r"(?:night|day|person|head|guest|pax|stay|nite)s?\b",
        re.IGNORECASE,
    ),
    # Rate unit preceding the figure -- "per night 12000"
    re.compile(
        r"\bper\s+(?:night|day|person|head|guest|pax|stay)s?\s*(?:is|:|at|-)?\s*[\d][\d,]{2,}",
        re.IGNORECASE,
    ),
]

# Phrases that promise or imply a concrete cost even without a figure.
# "It works out cheaper" is still a pricing statement the brand wants a human
# to make. Kept narrow to avoid flagging ordinary words like "free WiFi".
_PRICE_TALK_RE = re.compile(
    r"\b(?:the\s+)?(?:total|price|rate|tariff|cost|charge)\s+(?:is|will\s+be|works\s+out|comes\s+to)\b"
    r"|\bcosts?\s+(?:you\s+)?(?:about|around|roughly)?\s*[\d]"
    r"|\b(?:discount|off)\s+of\s+[\d]"
    r"|\b[\d]+\s*%\s*(?:discount|off)\b",
    re.IGNORECASE,
)


def detect_price(text: str) -> Optional[str]:
    """Return the first price-like mention found, or None.

    Used as a hard gate: any hit means the draft must not be auto-sent.
    """
    if not text:
        return None
    for pat in _PRICE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    m = _PRICE_TALK_RE.search(text)
    return m.group(0).strip() if m else None


_FIGURE_RE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.IGNORECASE)


def _to_int(raw: str, k: Optional[str]) -> Optional[int]:
    try:
        n = float(raw.replace(",", ""))
    except ValueError:
        return None
    if k:
        n *= 1000
    return int(round(n))


def money_figures(text: str) -> list[int]:
    """Every rupee-style figure the text states, as whole numbers ("Rs 12,000", "12k per night", "INR 9500")."""
    found: list[int] = []
    for pat in _PRICE_PATTERNS:
        for m in pat.finditer(text or ""):
            for num in _FIGURE_RE.finditer(m.group(0)):
                n = _to_int(num.group(1), num.group(2))
                if n is not None:
                    found.append(n)
    return found


def grounded_numbers(facts: list) -> set[int]:
    """Whole-number money values present in grounded facts, matched exactly.

    Only values stored under money-bearing keys count (a total, a nightly rate, an add-on price ...). Reading every number in the
    facts would let a fragment of an id or a headcount "support" an invented price.
    """
    nums: set[int] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in _MONEY_KEYS and not isinstance(val, (dict, list)) and val is not None:
                    for num in _FIGURE_RE.finditer(str(val)):
                        n = _to_int(num.group(1), None)
                        if n is not None:
                            nums.add(n)
                else:
                    walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(facts or [])
    return nums


def unsupported_figures(text: str, facts: list) -> list[int]:
    """Figures in the reply that no grounded fact states. Empty list = every price the reply quotes is a live figure."""
    allowed = grounded_numbers(facts)
    return [n for n in money_figures(text) if n not in allowed]


def strip_prices(text: str) -> str:
    """Remove price figures from free text (knowledge-base passages, uploaded rate cards) before the model sees them.

    A document's rate is whatever it said when it was written; the live rate comes from the rate tables. Letting the model see
    both is how an old price ends up in a reply.
    """
    out = text or ""
    for pat in _PRICE_PATTERNS:
        out = pat.sub("[rate: see live pricing or team to confirm]", out)
    return out


# Keys carrying money inside grounded_facts results.
_PRICE_KEYS = {
    "price_per_night", "price", "total", "subtotal", "gst", "tax",
    "advance_amount", "amount", "rate", "base_rate", "nightly_rate",
    "total_amount", "discount", "addon_total", "grand_total", "balance",
}


# Money-bearing keys that can carry a figure a reply is allowed to repeat (a superset of what redaction hides).
_MONEY_KEYS = _PRICE_KEYS | {"price_per_night", "per_night", "price_per_day", "unit_price", "deposit", "deposit_amount"}


def redact_price_facts(grounded_facts: list) -> list:
    """Strip money values out of grounded facts before prompt rendering.

    Availability is still useful ("yes, those dates are open") and is kept.
    The figures are removed so the model cannot repeat a number it was never
    supposed to see -- prompt instructions alone leave the number one
    instruction-following slip away from a guest's screen.
    """
    def _clean(obj):
        if isinstance(obj, dict):
            return {
                k: ("[withheld]" if k in _PRICE_KEYS and v is not None else _clean(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_clean(x) for x in obj]
        return obj

    return _clean(grounded_facts or [])


# ── Lead qualification ───────────────────────────────────────────────────────

# Ordered by how naturally they come up in conversation, not by importance --
# the prompt asks for at most two at a time, so order decides what gets asked
# first.
DETAIL_FIELDS = [
    ("name",             "their name"),
    ("dates",            "travel dates (check-in and check-out)"),
    ("guests",           "how many guests (adults and children)"),
    ("location",         "which property or destination they have in mind"),
    ("special_requests", "any special requests or occasion"),
]


def missing_lead_details(guest, inquiry, details: Optional[dict] = None) -> list[str]:
    """Which qualifying details are still unknown, as prompt-ready phrases.

    `details` are facts the guest stated in the conversation that have not reached the inquiry yet (the CRM fields are filled
    by a debounced background job, so a detail given a minute ago would otherwise be asked for again).
    """
    details = details or {}
    missing: list[str] = []

    name = (getattr(guest, "name", None) or "").strip()
    # Auto-created guests are often named from a handle/number rather than by
    # the person, so treat obvious placeholders as unknown.
    if not name or name.lower() in {"guest", "unknown", "instagram user", "whatsapp user"}:
        missing.append("their name")

    has_dates = bool(inquiry and getattr(inquiry, "check_in", None) and getattr(inquiry, "check_out", None)) \
        or bool(details.get("check_in") and details.get("check_out"))
    if not has_dates:
        missing.append("travel dates (check-in and check-out)")

    adults = (getattr(inquiry, "adults", None) if inquiry else None) or details.get("adults")
    if not adults:
        missing.append("how many guests (adults and children)")

    has_property = (bool(getattr(inquiry, "property_id", None)) if inquiry else False) \
        or bool(details.get("destination") or details.get("property_hint"))
    if not has_property:
        missing.append("which property or destination they have in mind")

    occasion = ((getattr(inquiry, "occasion", None) or "") if inquiry else "") or (details.get("occasion") or "")
    notes = (getattr(inquiry, "notes", None) or "") if inquiry else ""
    if not (occasion or notes):
        missing.append("any special requests or occasion")

    return missing


def is_qualified(guest, inquiry, details: Optional[dict] = None) -> bool:
    """True when enough is known to hand the lead to an agent.

    Special requests are explicitly not required -- waiting for a guest to
    volunteer an occasion would stall otherwise-ready handoffs.
    """
    blocking = set(missing_lead_details(guest, inquiry, details)) - {"any special requests or occasion"}
    return not blocking
