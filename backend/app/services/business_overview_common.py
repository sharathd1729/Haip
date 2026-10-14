"""Shared building blocks of the Business Overview: the request parameters and the filters every block applies.

Split out of business_overview_service.py to keep both files readable. Nothing here computes a business figure on its
own; it only builds the conditions (leads.new, bookings made, linked-stay narrowing) the service composes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.property import Stay
from app.services import dashboard_service, kpi_metrics, lead_metrics

CHANNEL_KEYS = ("whatsapp", "instagram", "facebook", "call", "organic_call", "website", "email", "walk_in", "referral", "ota", "other")
CHANNEL_ALIASES = {"voice": "call", "phone": "call"}


@dataclass
class Params:
    tid: str
    d_from: str
    d_to: str
    start: str                      # UTC instants of the IST day edges
    end: str
    prev_from: str
    prev_to: str
    prev_start: str
    prev_end: str
    property_id: Optional[str]
    channel: Optional[str]
    scope_user_id: Optional[str]    # None = whole workspace
    tenant_wide: bool
    can_bookings: bool
    can_revenue: bool
    trend: str = "day"             # chart bucket: day | week | month


def normalise_channel(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = CHANNEL_ALIASES.get(raw.lower(), raw.lower())
    if key not in CHANNEL_KEYS:
        raise ValueError(f"Invalid channel: {raw}")
    return key


def previous_period(d_from: str, d_to: str) -> tuple[str, str]:
    """The equal-length period immediately before [d_from, d_to]."""
    f, t = date.fromisoformat(d_from), date.fromisoformat(d_to)
    days = (t - f).days + 1
    prev_to = f - timedelta(days=1)
    return (prev_to - timedelta(days=days - 1)).isoformat(), prev_to.isoformat()


# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────────

def _change(current: float, previous: float) -> Optional[dict]:
    """Percent change, or None when there is no baseline (never 0% or -100% against an empty period)."""
    if not previous:
        return None
    pct = round((current - previous) / previous * 100, 1)
    return {"pct": pct, "direction": "up" if pct > 0 else "down" if pct < 0 else "neutral"}


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


def _money(p: Params, value: float) -> Optional[float]:
    return round(float(value), 2) if p.can_revenue else None


def _channel_condition(channel: str):
    sources = {k: [] for k in CHANNEL_KEYS}
    for raw, (key, _label) in dashboard_service._SOURCE_GROUPS.items():
        sources[key].append(InquirySource(raw))
    if channel != "other":
        return Inquiry.source.in_(sources[channel])
    mapped = [s for group in sources.values() for s in group]
    return or_(Inquiry.source.is_(None), ~Inquiry.source.in_(mapped))


def _lead_conditions(p: Params, start: str, end: str) -> list:
    conds = kpi_metrics.lead_filters(p.tid, start, end, scope_user_id=p.scope_user_id, property_id=p.property_id)
    if p.channel:
        conds.append(_channel_condition(p.channel))
    return conds


def _linked_stay_ids(p: Params):
    """A SELECT of the stays this viewer may count when the view is narrowed to an agent or a channel, else None.
    Narrowing goes through the PERSON (Stay.guest_id): the stays of the guests the filter selects (lead_metrics.people), by
    the guest's first-touch channel and owner. The booking's own record is the canonical link; Stay.inquiry_id is not needed."""
    if not (p.scope_user_id or p.channel):
        return None
    return (select(Stay.id).join(Guest, Guest.id == Stay.guest_id)
            .where(Stay.tenant_id == p.tid, *lead_metrics.people(p.tid, channel=p.channel, scope_user_id=p.scope_user_id)))


def people_filters(p: Params) -> dict:
    """The filters the lead metrics take, from the request."""
    return {"property_id": p.property_id, "channel": p.channel, "scope_user_id": p.scope_user_id}


def _stay_conditions(p: Params, start: str, end: str, statuses=kpi_metrics.OCCUPYING_STATUSES) -> list:
    conds = kpi_metrics.booking_filters(p.tid, start, end, property_id=p.property_id, statuses=statuses)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        conds.append(Stay.id.in_(scoped))
    return conds


def _ist_day(dt: datetime) -> date:
    return dashboard_service._ist_day(dt)

