"""Escalation policy — messages the AI must never answer on its own.

Some guest messages are commercial or reputational commitments in disguise.
"I want a refund", "I'll be taking this further legally", "put me through to
a manager" -- an autonomous reply to any of those can cost far more than the
feature is worth, and `complaint` was previously a recognised intent that
received no special handling whatsoever.

A match here does three things (in concierge_draft):
  - forces the draft to human review, so it can never auto-send
  - alerts the team, because these are time-sensitive
  - is recorded on the draft's log line for later audit

Deliberately keyword-based rather than model-based: this is the backstop
that has to hold when the model misjudges tone, so it must not depend on
the same model's judgement. False positives here are cheap (an agent reads
one extra message); false negatives are expensive.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# Grouped for readability and so the log line can say *why* it escalated.
DEFAULT_ESCALATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "refund_billing": (
        "refund", "money back", "chargeback", "charge back", "overcharged",
        "double charged", "wrong amount", "billing error", "dispute the charge",
        "unauthorised charge", "unauthorized charge",
    ),
    "legal": (
        "legal action", "lawyer", "advocate", "sue", "court", "consumer forum",
        "consumer court", "police", "fir", "defamation", "notice",
    ),
    "cancellation": (
        "cancel my booking", "cancel the booking", "cancel my stay",
        "cancel my reservation", "want to cancel", "need to cancel",
        "cancelling", "canceling",
    ),
    "complaint": (
        "unacceptable", "disgusting", "filthy", "worst experience", "terrible experience",
        "very disappointed", "extremely disappointed", "horrible", "pathetic",
        "cheated", "scam", "fraud", "misleading", "false advertising",
        "never coming back", "ruined our", "spoiled our",
    ),
    # NOTE: bare "manager"/"supervisor"/"owner" are handled by
    # _REQUEST_PATTERNS below, not here -- as plain keywords they fired on
    # ordinary questions like "do you have a manager on site 24/7?".
    "human_request": (
        "speak to a human", "talk to a human", "real person", "speak to someone",
        "escalate", "complaint number", "customer care", "who am i speaking",
    ),
    "safety_medical": (
        "ambulance", "hospital", "injured", "injury", "accident", "emergency",
        "fire", "theft", "stolen", "harassment", "unsafe", "assault",
    ),
    "review_threat": (
        "google review", "tripadvisor", "social media", "post about this",
        "expose", "viral", "twitter", "instagram post about",
    ),
}

# Words whose plain meaning is fine in this business and which would
# otherwise fire constantly. Checked as whole phrases before escalating.
_BENIGN_CONTEXTS = (
    "cancellation policy",   # asking about the policy is a normal FAQ
    "free cancellation",
    "cancel anytime",
    "no cancellation",
)


def _compile(keywords: Iterable[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for kw in keywords:
        kw = (kw or "").strip().lower()
        if not kw:
            continue
        # Word-boundary match so "fir" doesn't fire inside "first" and
        # "sue" doesn't fire inside "issue".
        out.append((kw, re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)", re.IGNORECASE)))
    return out


_DEFAULT_COMPILED: list[tuple[str, str, re.Pattern]] = [
    (category, kw, pat)
    for category, kws in DEFAULT_ESCALATION_KEYWORDS.items()
    for kw, pat in _compile(kws)
]

# Cases where the escalating signal is the *request*, not the noun. Asking
# whether a manager exists on site is a normal pre-booking question; asking
# to be put through to one is not.
_REQUEST_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("human_request", "ask for manager", re.compile(
        r"\b(?:speak|talk|connect|put me through|transfer|refer|get me|need|want|call)\b"
        r"[^.?!]{0,40}?\b(?:manager|supervisor|owner|senior|higher authority)\b",
        re.IGNORECASE,
    )),
    ("human_request", "ask for manager (imperative)", re.compile(
        r"\b(?:your|the)\s+(?:manager|supervisor)\b\s*(?:please|now|asap)\b"
        r"|\b(?:manager|supervisor)\s+please\b",
        re.IGNORECASE,
    )),
]


def detect_escalation(text: str, extra_keywords: Optional[Iterable[str]] = None) -> Optional[dict]:
    """Return {category, keyword} for the first escalation trigger, else None."""
    if not text or not text.strip():
        return None

    lowered = text.lower()

    # Strip benign phrases first so "what's your cancellation policy?" is not
    # treated as a cancellation request.
    scrubbed = lowered
    for phrase in _BENIGN_CONTEXTS:
        scrubbed = scrubbed.replace(phrase, " ")

    for category, keyword, pattern in _DEFAULT_COMPILED:
        if pattern.search(scrubbed):
            return {"category": category, "keyword": keyword}

    for category, keyword, pattern in _REQUEST_PATTERNS:
        if pattern.search(scrubbed):
            return {"category": category, "keyword": keyword}

    for keyword, pattern in _compile(extra_keywords or []):
        if pattern.search(scrubbed):
            return {"category": "tenant_custom", "keyword": keyword}

    return None


def tenant_keywords(tenant) -> list[str]:
    """Tenant's additional keywords, defensively normalised."""
    raw = getattr(tenant, "ai_escalation_keywords", None) or []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(k).strip() for k in raw if str(k or "").strip()]


# Intents that are never safe to answer autonomously, independent of any
# keyword match. `complaint` previously fell through to the ordinary reply
# path with no special routing at all.
NEVER_AUTONOMOUS_INTENTS = frozenset({"complaint"})


def should_escalate(text: str, intent: Optional[str], tenant) -> Optional[dict]:
    """Single entry point: keyword match OR an intent that always needs a human."""
    hit = detect_escalation(text, tenant_keywords(tenant))
    if hit:
        return hit
    if intent in NEVER_AUTONOMOUS_INTENTS:
        return {"category": "intent", "keyword": intent}
    return None
