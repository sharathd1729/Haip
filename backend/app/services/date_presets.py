"""
Relative date-range presets for Leads360 filters (restructure plan §3.1).

Resolved server-side in IST always -- HAIP is India-only, and computing
"last 7 days" client-side risks a preset silently shifting by a day when
the browser's local timezone isn't IST.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

IST = ZoneInfo("Asia/Kolkata")

VALID_PRESETS = {
    "today", "yesterday", "this_month", "last_month",
    "last_7d", "last_14d", "next_7d", "next_14d", "custom",
}


def today_ist() -> date:
    return datetime.now(IST).date()


def resolve_preset(preset: Optional[str]) -> tuple[Optional[date], Optional[date]]:
    """Return (from_date, to_date) for a named preset, inclusive of today."""
    if not preset or preset == "custom":
        return None, None
    today = today_ist()
    if preset == "today":
        return today, today
    if preset == "yesterday":
        yday = today - timedelta(days=1)
        return yday, yday
    if preset == "this_month":
        return today.replace(day=1), today
    if preset == "last_month":
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        return last_of_prev_month.replace(day=1), last_of_prev_month
    if preset == "last_7d":
        return today - timedelta(days=6), today
    if preset == "last_14d":
        return today - timedelta(days=13), today
    if preset == "next_7d":
        return today, today + timedelta(days=6)
    if preset == "next_14d":
        return today, today + timedelta(days=13)
    raise ValueError(f"Unknown date preset: {preset}")


def clean_date_str(value: Optional[str]) -> Optional[str]:
    """Normalise a raw query-param date string to None (empty/whitespace)
    or a validated 'YYYY-MM-DD' string. Raises ValueError on anything else
    -- callers should turn that into a 422, not let it reach a raw SQL
    comparison against a timestamptz column as an uncaught Postgres 503
    (confirmed live: a stray/malformed value in Leads360's custom date
    range surfaced as DataError('...invalid input syntax for type
    timestamp with time zone: ""') instead of a clean validation error)."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    date.fromisoformat(stripped)  # raises ValueError if malformed
    return stripped


def resolve_range(
    preset: Optional[str], explicit_from: Optional[str], explicit_to: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve a preset+custom-range pair into ISO date strings.
    Explicit from/to always win when preset is "custom" or unset; a named
    preset overrides explicit values (the UI shouldn't send both, but if it
    does, the preset is the more deliberate signal).
    """
    if preset and preset != "custom":
        d_from, d_to = resolve_preset(preset)
        return d_from.isoformat(), d_to.isoformat()
    return clean_date_str(explicit_from), clean_date_str(explicit_to)
