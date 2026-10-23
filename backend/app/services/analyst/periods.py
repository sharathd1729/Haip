"""Which days a report covers, in the workspace timezone (IST), and what it is compared with.

  daily_pulse     yesterday               vs the day before          baseline: the 28 days before yesterday
  weekly_brief    last full Mon-Sun week  vs the week before         baseline: the 4 weeks before that week
  monthly_review  last full month         vs the month before        baseline: the 3 months before that month

Bounds are IST calendar days turned into UTC instants (start of the first day, end of the last day inclusive), the same
rule every other HAIP report uses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from app.services.date_presets import IST


@dataclass(frozen=True)
class Window:
    d_from: date
    d_to: date

    @property
    def days(self) -> int:
        return (self.d_to - self.d_from).days + 1

    def bounds(self) -> tuple[datetime, datetime]:
        lo = datetime.combine(self.d_from, time.min, tzinfo=IST).astimezone(timezone.utc)
        hi = datetime.combine(self.d_to, time.max, tzinfo=IST).astimezone(timezone.utc)
        return lo, hi

    def out(self) -> dict:
        return {"from": self.d_from.isoformat(), "to": self.d_to.isoformat(), "days": self.days}


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _prev_month(d: date) -> date:
    return (_month_start(d) - timedelta(days=1)).replace(day=1)


def windows(kind: str, today: date) -> tuple[Window, Window, Window]:
    """(current, previous, baseline) for a report written on ``today`` (local date)."""
    if kind == "daily_pulse":
        cur = Window(today - timedelta(days=1), today - timedelta(days=1))
        prev = Window(cur.d_from - timedelta(days=1), cur.d_from - timedelta(days=1))
        base = Window(cur.d_from - timedelta(days=28), cur.d_from - timedelta(days=1))
    elif kind == "weekly_brief":
        monday = today - timedelta(days=today.weekday())
        cur = Window(monday - timedelta(days=7), monday - timedelta(days=1))
        prev = Window(cur.d_from - timedelta(days=7), cur.d_from - timedelta(days=1))
        base = Window(cur.d_from - timedelta(days=28), cur.d_from - timedelta(days=1))
    elif kind == "monthly_review":
        first = _prev_month(today)
        cur = Window(first, _month_start(today) - timedelta(days=1))
        p_first = _prev_month(first)
        prev = Window(p_first, first - timedelta(days=1))
        b_first = _prev_month(_prev_month(p_first))
        base = Window(b_first, first - timedelta(days=1))
    else:
        raise ValueError(f"unknown report kind {kind!r}")
    return cur, prev, base


def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(IST)
