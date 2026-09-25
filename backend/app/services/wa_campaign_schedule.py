"""Scheduling for WhatsApp campaigns.

`scheduled_at` is a string column. The old form saved whatever the browser's
datetime-local box produced -- a time with no timezone -- and nothing ever
read it, so scheduled campaigns never ran. Times are now stored as UTC ISO
strings; a time with no timezone is taken as India Standard Time, which is
what anyone typing it means.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))
MAX_AHEAD = timedelta(days=180)
GRACE = timedelta(minutes=2)          # "now" typed a moment ago is still fine


class ScheduleError(ValueError):
    """A schedule the user has to fix; message is safe to show."""


def parse_time(value: Optional[str]) -> Optional[datetime]:
    """Any stored or submitted time as an aware UTC datetime; None if empty/unreadable."""
    if not value or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def normalize_schedule(value: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """Validate a time someone typed and return it as a UTC ISO string.
    None for "no schedule". Raises ScheduleError for a time in the past or
    absurdly far ahead, or one that can't be read."""
    if value is None or not str(value).strip():
        return None
    now = now or datetime.now(timezone.utc)
    dt = parse_time(value)
    if dt is None:
        raise ScheduleError("Couldn't read that date and time.")
    if dt < now - GRACE:
        raise ScheduleError("That time has already passed. Pick a time in the future.")
    if dt > now + MAX_AHEAD:
        raise ScheduleError("Schedule within the next 6 months.")
    return dt.isoformat()


def is_due(value: Optional[str], now: Optional[datetime] = None) -> bool:
    dt = parse_time(value)
    return dt is not None and dt <= (now or datetime.now(timezone.utc))
