"""
D1 — Opt-out keyword detection (English + Hindi + Marathi).

Rules (PR-2, docs/ai/SALES_AGENT_CURRENT_STATE.md §2 item 2; tests/test_increment1_defect_specs.py section B):
- Opt-out = the WHOLE message is a stop keyword ("STOP", "stop.", "बंद करो"), or the message carries a phrase that can
  only mean "stop messaging me" ("unsubscribe", "stop sending me messages", "don't message me"). A word inside a sentence
  is never enough: "cancel my booking", "our first stop is Hubli", "end of December" are about the trip, not about us.
- "cancel" / "end" / "remove" / "block" / "quit" are not stop keywords even alone: too often they are about a booking.
- Opt-in = the WHOLE message is an opt-in keyword. "yes" / "हाँ" / "begin" answer any question; they are never consent.
"""
import re
from dataclasses import dataclass
from typing import Literal

# ── Keyword sets ──────────────────────────────────────────────────────────────

# The whole message must be one of these.
OPT_OUT_KEYWORDS: frozenset[str] = frozenset({
    "stop", "unsubscribe", "opt out", "optout", "stop messages", "stop messaging",
    # Hindi (Devanagari)
    "बंद करो", "रोको", "बंद",
    # Marathi
    "नको",
    # Common short-form Hindi (transliterated)
    "band karo", "roko",
})

# Anywhere in the message (whole words): phrases with no other meaning in a trip conversation.
OPT_OUT_PHRASES: tuple[str, ...] = (
    "unsubscribe", "opt out", "optout",
    "stop messaging", "stop sending me", "stop texting", "stop contacting", "stop calling me",
    "do not contact", "don't contact", "dont contact",
    "do not message me", "don't message me", "dont message me",
    "do not text me", "don't text me", "dont text me",
    "no more messages", "send no more messages",
    "messages band karo", "message band karo",
)

OPT_IN_KEYWORDS: frozenset[str] = frozenset({
    "start", "resubscribe", "opt in", "optin", "subscribe",
    # Hindi
    "शुरू करो", "shuru karo",
})


@dataclass
class OptOutResult:
    matched: bool
    direction: Literal["opt_out", "opt_in"] | None   # None when matched=False
    matched_keyword: str | None
    is_whole_message: bool


def _normalize(text: str) -> str:
    """Lower case, punctuation to spaces, single spaces. Punctuation only: a \W class would also strip Devanagari vowel signs."""
    text = text.lower().replace("’", "'")
    return " ".join(re.sub(r"[!-&(-/:-@\[-`{-~…।]+", " ", text).split())


def _has_phrase(body: str, phrase: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", body, re.UNICODE))


def detect_opt_out(body: str) -> OptOutResult:
    """
    Analyze a message body for opt-out / opt-in intent.

    Returns OptOutResult. matched=True and direction set on detection.
    Priority: opt_out > opt_in (safety: if guest says "stop opt in", treat as stop).
    """
    normalized = _normalize(body or "")

    if normalized in OPT_OUT_KEYWORDS:
        return OptOutResult(matched=True, direction="opt_out", matched_keyword=normalized, is_whole_message=True)
    for phrase in OPT_OUT_PHRASES:
        if _has_phrase(normalized, phrase):
            return OptOutResult(matched=True, direction="opt_out", matched_keyword=phrase, is_whole_message=False)

    if normalized in OPT_IN_KEYWORDS:
        return OptOutResult(matched=True, direction="opt_in", matched_keyword=normalized, is_whole_message=True)

    return OptOutResult(matched=False, direction=None, matched_keyword=None, is_whole_message=False)
