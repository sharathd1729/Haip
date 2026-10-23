"""Who wrote a conversation message, for every prompt that shows the AI a thread (concierge reply, intent classifier, lead summary).

Live bug (Rathaa, Oct 2026): our own WhatsApp campaign ("two caravans free ... 8 guests each ... tell us your dates") reached the
models as a plain [OUTBOUND] line. The lead's trip details came back as "8 adults" and the concierge offered "open weekend dates
for 8 adults" to a guest who had only asked about a barter collaboration. Every line now names its author, and a headcount that
only WE wrote is dropped in code (keep_guest_headcount), whatever the model returned.

Pure functions; no database, no network.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

GUEST = "GUEST"
TEAM = "US: TEAM MEMBER"
AI = "US: AI ASSISTANT"
AUTOMATED = "US: AUTOMATED MESSAGE"
CAMPAIGN = "US: CAMPAIGN BROADCAST"

_AI_KINDS = ("ai_auto", "ai_approved", "ai_holding")
_AUTOMATED_KINDS = ("playbook", "system")


def author_of(direction, *, sender_kind: Optional[str] = None, sender_name: Optional[str] = None,
              is_ai_generated: Optional[bool] = None, channel_metadata=None) -> str:
    """GUEST, or which of our senders wrote it. A campaign is recognised on rows written before ``sender_kind`` existed
    (migration 151) by its metadata or its "Campaign: <name>" sender name (wa_campaign_inbox.record_send)."""
    if str(getattr(direction, "value", direction) or "").lower() == "inbound":
        return GUEST
    kind = (sender_kind or "").lower()
    meta = channel_metadata if isinstance(channel_metadata, dict) else {}
    if kind == "campaign" or meta.get("kind") == "campaign" or (sender_name or "").startswith("Campaign:"):
        return CAMPAIGN
    if kind in _AUTOMATED_KINDS:
        return AUTOMATED
    if is_ai_generated or kind in _AI_KINDS:
        return AI
    return TEAM


def author(message) -> str:
    """author_of() for a Message row."""
    return author_of(getattr(message, "direction", None), sender_kind=getattr(message, "sender_kind", None),
                     sender_name=getattr(message, "sender_name", None),
                     is_ai_generated=getattr(message, "is_ai_generated", None),
                     channel_metadata=getattr(message, "channel_metadata", None))


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_NUM = r"(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")"
_NUMBER_RE = re.compile(r"(?<![\w.,])" + _NUM + r"(?!\w|[.,]\d)", re.IGNORECASE)
# What WE wrote counts only where a number is a headcount ("8 guests each", "16 spots", "for 8 adults", "group of 6"): "two
# caravans" in a campaign must not discard a guest's "me and my wife" (2).
_PEOPLE = r"(?:guests?|people|persons?|pax|adults?|children|kids|spots|seats|members|friends|travell?ers|heads)"
_OUR_HEADCOUNT_RE = re.compile(r"\b" + _NUM + r"\s+(?:[a-z]+\s+)?" + _PEOPLE + r"\b|\b(?:group|party|family|batch) of\s+" + _NUM + r"\b",
                               re.IGNORECASE)
HEADCOUNT_KEYS = ("adults", "children", "party_size")


def _value(token: str) -> int:
    return _NUMBER_WORDS[token.lower()] if token.lower() in _NUMBER_WORDS else int(token)


def _numbers_in(texts: Iterable[str]) -> set[int]:
    """Every number the guest wrote, in digits or words."""
    return {_value(m.group(1)) for text in texts for m in _NUMBER_RE.finditer(text or "")}


def _headcounts_in(texts: Iterable[str]) -> set[int]:
    """Numbers we wrote as a headcount."""
    return {_value(m.group(1) or m.group(2)) for text in texts for m in _OUR_HEADCOUNT_RE.finditer(text or "")}


def _as_int(value) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def keep_guest_headcount(values: dict, guest_texts: Iterable[str], our_texts: Iterable[str],
                         keys: tuple = HEADCOUNT_KEYS) -> tuple[dict, list[str]]:
    """(values without any headcount that only WE wrote, the keys dropped).

    A headcount is dropped when we wrote that number as a headcount (a campaign's "8 guests each", the AI's own "for 8
    adults") and the guest wrote that number nowhere. A number the guest also wrote, or one nobody wrote (the guest said
    "me and my wife"), is kept: this is a narrow guard against our text being read back as theirs, not a second extractor."""
    if not values:
        return values, []
    guest_nums = _numbers_in(guest_texts)
    our_nums = _headcounts_in(our_texts)
    out, dropped = dict(values), []
    for key in keys:
        n = _as_int(out.get(key))
        if n is not None and n > 0 and n in our_nums and n not in guest_nums:
            out.pop(key)
            dropped.append(key)
    return out, dropped
