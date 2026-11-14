"""AI tags on leads (inquiries.tags), written by the lead summary (workers/tasks/generate_ai_summary.py).

The model may only pick tags from VOCABULARY: a fixed list keeps segments countable ("how many anniversary leads are
ready to book?") where free text would scatter into "anniv", "anniversary trip", "wedding anniversary". Tags describe
what the GUEST said or showed; a tag that needs a guess is left out (the summary's own rules).

inquiries.tags may also hold tags a person added. The AI only ever replaces the tags IT wrote last time
(`ai_analysis["ai_tags"]`), so a person's tag survives every summary.
"""

from __future__ import annotations

VOCABULARY: dict[str, tuple[str, ...]] = {
    "Group": ("couple", "family", "friends", "corporate", "solo", "large group"),
    "Occasion": ("anniversary", "birthday", "honeymoon", "wedding", "proposal", "festival", "workcation"),
    "Buying signal": ("ready to book", "comparing options", "price sensitive", "just browsing", "flexible dates",
                      "last minute", "repeat guest", "referred"),
    "Needs": ("pets", "kids", "senior citizens", "accessibility", "food preferences", "decoration", "transport"),
    "Concern": ("price objection", "availability concern", "trust concern", "slow reply complaint"),
}
ALL_TAGS: tuple[str, ...] = tuple(t for tags in VOCABULARY.values() for t in tags)
_LOOKUP = {t.lower(): t for t in ALL_TAGS}
MAX_TAGS = 6

PROMPT_LINE = (
    '"tags": ["<0 to 6 tags that fit THIS guest, chosen ONLY from this list, spelled exactly: '
    + ", ".join(ALL_TAGS)
    + '. Only what the guest said or clearly showed; [] if none fit>"],'
)


def clean(raw) -> list[str]:
    """Only known tags, in their canonical spelling, de-duplicated, at most MAX_TAGS."""
    out: list[str] = []
    for x in raw if isinstance(raw, list) else []:
        tag = _LOOKUP.get(str(x).strip().lower()) if isinstance(x, (str, int, float)) else None
        if tag and tag not in out:
            out.append(tag)
    return out[:MAX_TAGS]


def merge(current, previous_ai, new_ai: list[str]) -> list[str]:
    """inquiries.tags after a summary: a person's tags (anything the AI did not write last time) + the new AI tags."""
    old_ai = {str(t) for t in (previous_ai or [])}
    kept = [t for t in (current or []) if isinstance(t, str) and t not in old_ai]
    return kept + [t for t in new_ai if t not in kept]


def check(tag: str | None) -> str | None:
    """A tag filter value -> its canonical spelling; ValueError for a tag outside the vocabulary (the caller answers 422)."""
    if not tag:
        return None
    found = _LOOKUP.get(tag.strip().lower())
    if not found:
        raise ValueError(f"Unknown tag: {tag}")
    return found


def has_tag(column, tag: str):
    """SQL: this JSON list column holds `tag` (a vocabulary tag, so no LIKE wildcards inside). Works on PG and SQLite."""
    from sqlalchemy import String, cast

    return cast(column, String).like(f'%"{tag}"%')
