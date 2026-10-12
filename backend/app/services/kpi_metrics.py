"""Canonical, shared KPI calculations (Dashboards & Reports, phase 1).

Only metrics whose definition is the same everywhere it is used live here. A metric whose consumers disagree
(revenue, bookings, conversion, occupancy as a percentage, response time, answered calls) is NOT here on purpose:
the disagreement is recorded in docs/analytics/KPI_METRIC_CATALOGUE.md as a business decision, and picking a winner
in code would silently change a number somebody already reads.

Rules every function here follows:
  * tenant first: every query is filtered on ``tenant_id`` and has no way to skip it;
  * time is explicit: callers pass the period bounds (the IST day boundaries converted to UTC by
    ``date_presets.ist_range_to_utc``), this module never decides "today";
  * the value a caller gets back for an empty period is 0, never None or an error.

Registry: ``CANONICAL_METRICS`` is the machine-readable index of what is shared. tests/services/test_kpi_metrics.py
fails if a metric listed here is missing from the catalogue document, so code and documentation cannot drift apart.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Optional, Union

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.property import Stay
from app.models.stay_finance import StayPayment

Bound = Union[datetime, str]

CANONICAL_METRICS: dict[str, dict[str, str]] = {
    "leads.new": {
        "name": "New leads",
        "definition": "Enquiries created in the period that were not marked unqualified (spam).",
        "date_basis": "Inquiry.created_at, period bounds in UTC converted from IST calendar days",
        "function": "lead_filters / count_leads",
    },
    "stays.occupied_nights": {
        "name": "Occupied nights",
        "definition": "Nights in [window_start, window_end) covered by a stay, one night per night slept, "
                      "check-out day not counted.",
        "date_basis": "Stay.check_in / Stay.check_out (calendar dates), half-open window",
        "function": "occupied_nights",
    },
    "stays.booked": {
        "name": "Bookings made",
        "definition": "Stays created in the period whose status is confirmed, checked in or checked out (cancelled "
                      "excluded). Count, and the sum of Stay.total_amount (the stay charge, add-ons not included).",
        "date_basis": "Stay.created_at, period bounds in UTC converted from IST calendar days",
        "function": "booking_filters / booked_totals",
    },
    "payments.collected": {
        "name": "Cash collected",
        "definition": "Payments received (kind payment) with a payment date in the period, and refunds (kind refund) "
                      "paid out in the period, kept as two separate figures.",
        "date_basis": "StayPayment.paid_on (a calendar date), inclusive IST dates",
        "function": "payment_totals",
    },
}

# What "unqualified" means is decided upstream (lead_qualification_service); this module only honours it.
UNQUALIFIED = "unqualified"

# Stays that count as nights actually or expected to be slept. The executive dashboard has always used this set for
# occupancy. (Other revenue/booking consumers use different status rules; see the catalogue.)
OCCUPYING_STATUSES: tuple[str, ...] = ("confirmed", "checked_in", "checked_out")


def as_datetime(value: Bound) -> datetime:
    """A period bound as an aware UTC datetime.

    Callers have always passed either a datetime or an ISO string (``ist_range_to_utc`` returns both forms). Strings
    are parsed here so every database compares the same instant: comparing an ISO string with a stored timestamp
    is only correct on PostgreSQL, SQLite compares the text and gets the 'T' versus ' ' separator wrong."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


# ── leads.new ────────────────────────────────────────────────────────────────────────────────────────────────

def lead_filters(
    tenant_id: str,
    start: Bound,
    end: Bound,
    *,
    scope_user_id: Optional[str] = None,
    property_id: Optional[str] = None,
) -> list:
    """SQL conditions for "new leads" in [start, end] (both inclusive), for one tenant.

    ``scope_user_id`` limits to enquiries assigned to that user (an agent's own leads); ``property_id`` to one
    property. Use as ``db.query(...).filter(*lead_filters(...))`` so a caller can select whatever columns it needs
    (count, per-day bucket, per-source group) without re-stating the definition."""
    conditions = [
        Inquiry.tenant_id == tenant_id,
        Inquiry.created_at >= as_datetime(start),
        Inquiry.created_at <= as_datetime(end),
        Inquiry.qualification_status != UNQUALIFIED,
    ]
    if scope_user_id:
        conditions.append(Inquiry.assigned_to == scope_user_id)
    if property_id:
        conditions.append(Inquiry.property_id == property_id)
    return conditions


def count_leads(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> int:
    return db.query(func.count(Inquiry.id)).filter(*lead_filters(tenant_id, start, end, **filters)).scalar() or 0


# ── stays.occupied_nights ────────────────────────────────────────────────────────────────────────────────────

def occupied_nights(
    db: Session,
    tenant_id: str,
    window_start: date,
    window_end: date,
    *,
    property_ids: Optional[Iterable[str]] = None,
    statuses: Iterable[str] = OCCUPYING_STATUSES,
) -> int:
    """Total nights occupied inside the half-open window [window_start, window_end).

    A stay from 10th (check-in) to 13th (check-out) occupies the nights of the 10th, 11th and 12th. Only the part of
    a stay inside the window counts. Cancelled stays are excluded because ``statuses`` does not list them; callers
    that need a different rule pass their own ``statuses`` and say so in the catalogue."""
    if window_end <= window_start:
        return 0
    query = db.query(Stay.check_in, Stay.check_out).filter(
        Stay.tenant_id == tenant_id,
        Stay.status.in_(list(statuses)),
        Stay.check_in < window_end,
        Stay.check_out > window_start,
    )
    if property_ids is not None:
        query = query.filter(Stay.property_id.in_(list(property_ids)))
    total = 0
    for check_in, check_out in query.all():
        first = max(check_in, window_start)
        last = min(check_out, window_end)
        total += max(0, (last - first).days)
    return total


# ── stays.booked ─────────────────────────────────────────────────────────────────────────────────────────────

def booking_filters(
    tenant_id: str,
    start: Bound,
    end: Bound,
    *,
    property_id: Optional[str] = None,
    statuses: Iterable[str] = OCCUPYING_STATUSES,
) -> list:
    """SQL conditions for bookings made in [start, end] (both inclusive), for one tenant.

    "Made" is judged on the day the booking was created, not the day the guest arrives (the two answer different
    questions; the catalogue keeps both, see D-03). Pass the result to ``db.query(...).filter(*...)`` and join
    whatever else the caller needs (the linked lead, payments)."""
    conditions = [
        Stay.tenant_id == tenant_id,
        Stay.created_at >= as_datetime(start),
        Stay.created_at <= as_datetime(end),
        Stay.status.in_(list(statuses)),
    ]
    if property_id:
        conditions.append(Stay.property_id == property_id)
    return conditions


def booked_totals(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> tuple[int, float]:
    """(number of bookings made, total stay charge) in the period."""
    count, value = db.query(func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0)).filter(
        *booking_filters(tenant_id, start, end, **filters)
    ).one()
    return int(count or 0), float(value or 0)


# ── payments.collected ───────────────────────────────────────────────────────────────────────────────────────

def payment_totals(
    db: Session,
    tenant_id: str,
    day_from: date,
    day_to: date,
    *,
    property_id: Optional[str] = None,
    extra_filters: Iterable = (),
) -> dict[str, float]:
    """Cash received and cash refunded with a payment date in [day_from, day_to] (inclusive).

    Refunds are NOT netted into ``collected``: the caller shows both and may add ``net``. Payments on cancelled
    stays still count, because the money really moved. ``extra_filters`` lets a caller restrict to some stays
    (for example only those linked to one agent's leads) without re-stating the definition."""
    collected = func.coalesce(func.sum(case((StayPayment.kind == "payment", StayPayment.amount), else_=0)), 0)
    refunded = func.coalesce(func.sum(case((StayPayment.kind == "refund", StayPayment.amount), else_=0)), 0)
    q = (
        db.query(collected, refunded)
        .join(Stay, Stay.id == StayPayment.stay_id)
        .filter(StayPayment.tenant_id == tenant_id, Stay.tenant_id == tenant_id,
                StayPayment.paid_on >= day_from, StayPayment.paid_on <= day_to)
    )
    if property_id:
        q = q.filter(Stay.property_id == property_id)
    for condition in extra_filters:
        q = q.filter(condition)
    got, back = q.one()
    got, back = float(got or 0), float(back or 0)
    return {"collected": got, "refunded": back, "net": got - back}
