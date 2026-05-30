"""
Intent normalizer — maps raw occasion/text strings to 10 standard intent buckets.

No LLM required — pure keyword + rule-based normalization.
Called by:
  - classify_intent Celery task (batch nightly normalization)
  - analytics_intelligence endpoint (inline classification of un-tagged records)
"""

from __future__ import annotations

# 10 standard intent buckets
INTENT_BUCKETS = [
    "honeymoon",
    "anniversary",
    "birthday",
    "friends_trip",
    "workcation",
    "corporate",
    "family_vacation",
    "long_stay",
    "weekend_getaway",
    "other",
]

# Keyword rules — ordered by priority (first match wins)
_RULES = [
    ("honeymoon",       ["honeymoon", "newlywed", "just married", "newlyweds"]),
    ("anniversary",     ["anniversary", "surprise trip", "surprise vacation", "couple trip"]),
    ("birthday",        ["birthday", "bday", "birth day", "b-day", "celebration", "celebrate birthday"]),
    ("corporate",       ["corporate", "team outing", "team offsite", "company trip", "offsite", "team building", "business trip"]),
    ("workcation",      ["workcation", "work from", "remote work", "laptop", "zoom calls", "work trip", "extended work"]),
    ("friends_trip",    ["friends", "gang trip", "boys trip", "girls trip", "friend group", "batchmates", "colleagues trip"]),
    ("family_vacation", ["family", "kids", "children", "family vacation", "family trip", "parents", "grandparents"]),
]

# Long stay / weekend getaway require stay length context (passed separately)
_LONG_STAY_NIGHTS = 7
_WEEKEND_GETAWAY_NIGHTS = 2


def normalize_intent(
    occasion_text: str | None,
    stay_nights: int | None = None,
    check_in_weekday: int | None = None,  # 0=Monday … 6=Sunday
) -> str:
    """
    Map raw occasion text + stay metadata to a standard intent bucket.

    Priority:
      1. Keyword match on occasion_text
      2. Long stay (nights >= 7)
      3. Weekend getaway (nights <= 2 AND check-in Fri/Sat)
      4. "other"
    """
    text = (occasion_text or "").lower().strip()

    for bucket, keywords in _RULES:
        if any(kw in text for kw in keywords):
            return bucket

    # Duration-based fallback
    if stay_nights is not None:
        if stay_nights >= _LONG_STAY_NIGHTS:
            return "long_stay"
        if stay_nights <= _WEEKEND_GETAWAY_NIGHTS and check_in_weekday in (4, 5):  # Friday or Saturday
            return "weekend_getaway"

    return "other"


def batch_normalize(records: list[dict]) -> list[dict]:
    """
    Normalize a list of {occasion, stay_nights?, check_in_weekday?} dicts.
    Returns same list with 'intent_tag' key added.
    """
    for r in records:
        r["intent_tag"] = normalize_intent(
            r.get("occasion"),
            r.get("stay_nights"),
            r.get("check_in_weekday"),
        )
    return records
