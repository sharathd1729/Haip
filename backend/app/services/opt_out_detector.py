"""
D1 — Opt-out keyword detection (English + Hindi + Marathi).

Rules:
- Case-insensitive exact-word match OR whole-message-equals-keyword.
- "STOPPED at hotel" → no match (substring across word boundaries).
- "STOP" alone → match.
"""
import re
from dataclasses import dataclass
from typing import Literal

# ── Keyword sets ──────────────────────────────────────────────────────────────

OPT_OUT_KEYWORDS: frozenset[str] = frozenset({
    # English
    "stop", "unsubscribe", "opt out", "optout", "remove",
    "cancel", "end", "quit", "block",
    # Hindi (Devanagari)
    "बंद करो", "रोको", "बंद",
    # Marathi
    "नको",
    # Common short-form Hindi (transliterated)
    "band karo", "roko",
})

OPT_IN_KEYWORDS: frozenset[str] = frozenset({
    "start", "resubscribe", "opt in", "optin", "subscribe",
    "yes", "begin",
    # Hindi
    "शुरू करो", "हाँ",
    "shuru karo",
})


@dataclass
class OptOutResult:
    matched: bool
    direction: Literal["opt_out", "opt_in"] | None   # None when matched=False
    matched_keyword: str | None
    is_whole_message: bool


def _normalize(text: str) -> str:
    return text.strip().lower()


def _is_whole_word_match(body: str, keyword: str) -> bool:
    """Check if keyword appears as a whole word (or phrase) in body."""
    escaped = re.escape(keyword)
    pattern = r"(?<!\w)" + escaped + r"(?!\w)"
    return bool(re.search(pattern, body, re.IGNORECASE | re.UNICODE))


def detect_opt_out(body: str) -> OptOutResult:
    """
    Analyze a message body for opt-out / opt-in intent.

    Returns OptOutResult. matched=True and direction set on detection.
    Priority: opt_out > opt_in (safety: if guest says "stop opt in", treat as stop).
    """
    normalized = _normalize(body)
    is_whole = False

    # Check opt-out keywords first (higher priority)
    for kw in OPT_OUT_KEYWORDS:
        kw_lower = kw.lower()
        # Whole-message equality check
        if normalized == kw_lower:
            return OptOutResult(matched=True, direction="opt_out", matched_keyword=kw, is_whole_message=True)
        # Whole-word match (multi-word phrases allowed as substring)
        if " " in kw and kw_lower in normalized:
            return OptOutResult(matched=True, direction="opt_out", matched_keyword=kw, is_whole_message=False)
        if " " not in kw and _is_whole_word_match(normalized, kw_lower):
            return OptOutResult(matched=True, direction="opt_out", matched_keyword=kw, is_whole_message=False)

    # Check opt-in keywords
    for kw in OPT_IN_KEYWORDS:
        kw_lower = kw.lower()
        if normalized == kw_lower:
            return OptOutResult(matched=True, direction="opt_in", matched_keyword=kw, is_whole_message=True)
        if " " in kw and kw_lower in normalized:
            return OptOutResult(matched=True, direction="opt_in", matched_keyword=kw, is_whole_message=False)
        if " " not in kw and _is_whole_word_match(normalized, kw_lower):
            return OptOutResult(matched=True, direction="opt_in", matched_keyword=kw, is_whole_message=False)

    return OptOutResult(matched=False, direction=None, matched_keyword=None, is_whole_message=False)
