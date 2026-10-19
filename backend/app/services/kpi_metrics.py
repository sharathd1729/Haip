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
from app.models.stay_finance import StayAddOn, StayPayment

Bound = Union[datetime, str]

CANONICAL_METRICS: dict[str, dict[str, str]] = {
    "leads.new": {
        "name": "New enquiries (legacy name)",
        "definition": "Enquiry RECORDS created in the period that were not marked unqualified (spam). This counts records, not "
                      "people: one person with three enquiries is three. For people see leads.identified_new.",
        "date_basis": "Inquiry.created_at, period bounds in UTC converted from IST calendar days",
        "function": "lead_filters / count_leads",
    },
    "conversations.new": {
        "name": "New conversations",
        "definition": "Conversations opened in the period (internal notes threads excluded). Interactions, not people.",
        "date_basis": "Conversation.created_at, IST days as UTC instants",
        "function": "lead_metrics.count_conversations",
    },
    "contacts.unidentified": {
        "name": "Contacts without a phone number",
        "definition": "People first heard from in the period who still have no usable phone number. Not leads.",
        "date_basis": "Guest.created_at; Guest.lead_identified_at IS NULL now",
        "function": "lead_metrics.count_unidentified_contacts",
    },
    "leads.identified_new": {
        "name": "New leads",
        "definition": "Unique people (guests) whose usable phone number was captured in the period: their first time as a lead.",
        "date_basis": "Guest.lead_identified_at, IST days as UTC instants",
        "function": "lead_metrics.count_new_leads / new_leads_conditions",
    },
    "leads.identified_active": {
        "name": "Leads active in the period",
        "definition": "Unique leads (phone known by the end of the period) with a message, a call or a new enquiry in the period.",
        "date_basis": "Message / Call / Inquiry created_at in the period",
        "function": "lead_metrics.count_active_leads",
    },
    "leads.qualified_new": {
        "name": "Qualified leads",
        "definition": "Of the new leads, those with a non-spam enquiry sitting in a pipeline stage of category valid, as of now.",
        "date_basis": "Guest.lead_identified_at (cohort)",
        "function": "lead_metrics.count_qualified_new",
    },
    "enquiries.created": {
        "name": "Enquiries (records)",
        "definition": "Enquiry records created in the period, with how many were repeat enquiries from a person who had enquired before.",
        "date_basis": "Inquiry.created_at, IST days as UTC instants",
        "function": "lead_metrics.enquiry_counts",
    },
    "leads.conversion_cohort": {
        "name": "Lead to booking (cohort)",
        "definition": "Of the people who became leads in the period, the share that has a live booking so far. Numerator and "
                      "denominator are both people from the same cohort; it is never bookings in the period over leads in the period.",
        "date_basis": "Guest.lead_identified_at (cohort); bookings counted whenever they were made",
        "function": "lead_metrics.cohort / lead_to_booking",
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
    "leads.qualified_dated": {
        "name": "Qualified leads (phone + check-in date)",
        "definition": "Of the new leads (leads.identified_new), the people with a non-spam enquiry that carries a check-in date, as "
                      "of now. The owner dashboard's 'Qualified leads' (19 Oct 2026); leads.qualified_new (valid stage) is kept for "
                      "the journey band.",
        "date_basis": "Guest.lead_identified_at (cohort), IST days as UTC instants",
        "function": "lead_metrics.count_qualified_dated",
    },
    "stays.booked_value": {
        "name": "Booked value (rental + add-ons)",
        "definition": "For the bookings made in the period (stays.booked): rental = sum of Stay.total_amount (the stay charge), "
                      "add-ons = sum of StayAddOn quantity x unit price on those bookings, booked value = rental + add-ons. The "
                      "monthly target is measured on it (D-24).",
        "date_basis": "Stay.created_at, IST calendar days as UTC instants",
        "function": "booked_value / booked_value_rows",
    },
    "payments.collected": {
        "name": "Payment received",
        "definition": "Payments received (kind payment) with a payment date in the period, and refunds (kind refund) "
                      "paid out in the period, kept as two separate figures.",
        "date_basis": "StayPayment.paid_on (a calendar date), inclusive IST dates",
        "function": "payment_totals",
    },
    # Impact view (catalogue section 14). Computed in impact_metrics.py; listed here so the registry stays the one index.
    "replies.first_response": {
        "name": "First reply time",
        "definition": "Per guest turn (a guest message after our reply, after 24 h of silence, or first in the chat; WhatsApp "
                      "Cloud API, personal WhatsApp mirror and Instagram; groups excluded): time to the first outbound message that "
                      "really went out (not an internal note, not failed/rejected/pending/queued). Median and p90 over answered "
                      "turns; answered within 5/15/60 min over all turns. Split by channel and by responder (AI, staff with an AI "
                      "draft, staff). Turns younger than 60 minutes are left out.",
        "date_basis": "the guest message's created_at, IST days as UTC instants",
        "function": "impact_metrics.first_replies / guest_turns",
    },
    "replies.after_hours": {
        "name": "After-hours replies",
        "definition": "Guest turns (as replies.first_response) that started outside business hours (Tenant.business_hours, else "
                      "the tenant_tz defaults), the share answered within 15 min, and the share of the answered ones the AI sent "
                      "on its own.",
        "date_basis": "the guest message's created_at, judged in the workspace timezone",
        "function": "impact_metrics.first_replies",
    },
    "leads.quoted_cohort": {
        "name": "Leads quoted (cohort)",
        "definition": "Of the people who became leads in the period, those with a quote so far (an inquiry_quotes row or "
                      "Inquiry.quoted_at on any of their enquiries).",
        "date_basis": "Guest.lead_identified_at (cohort); quotes counted whenever they were made",
        "function": "impact_metrics.funnel",
    },
    "calls.missed_returned": {
        "name": "Missed calls called back",
        "definition": "Inbound calls missed in the period (call_status_service rule), those with recovered_by_call_id (returned), "
                      "and the median time from the missed call to the callback. All IVR providers counted.",
        "date_basis": "Call.created_at of the missed call, IST days as UTC instants",
        "function": "impact_metrics.missed_calls",
    },
    "enquiries.lost": {
        "name": "Enquiries lost, by reason",
        "definition": "Enquiry records (not spam) now in a closed-lost stage that entered it in the period, grouped by "
                      "Inquiry.lost_reason (empty = Not recorded). Records, not people.",
        "date_basis": "Inquiry.current_stage_entered_at (else updated_at)",
        "function": "impact_metrics.lost_enquiries",
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


# ── stays.booked_value (D-24) ───────────────────────────────────────────────────────────────────────────────

def booked_value_rows(db: Session, tenant_id: str, start: Bound, end: Bound, *, property_id: Optional[str] = None,
                      extra_filters: Iterable = ()) -> list[dict]:
    """One row per booking made in the period: {stay_id, property_id, inquiry_id, rental, add_ons}. Callers group these in Python
    (by property, by agent) so every split adds up to ``booked_value``."""
    conds = [*booking_filters(tenant_id, start, end, property_id=property_id), *extra_filters]
    stays = db.query(Stay.id, Stay.property_id, Stay.inquiry_id, Stay.total_amount).filter(*conds).all()
    if not stays:
        return []
    addons = dict(db.query(StayAddOn.stay_id, func.coalesce(func.sum(StayAddOn.quantity * StayAddOn.unit_price), 0))
                  .filter(StayAddOn.tenant_id == tenant_id, StayAddOn.stay_id.in_([s[0] for s in stays]))
                  .group_by(StayAddOn.stay_id).all())
    return [{"stay_id": sid, "property_id": pid, "inquiry_id": iid, "rental": float(amount or 0), "add_ons": float(addons.get(sid) or 0)}
            for sid, pid, iid, amount in stays]


def booked_value(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> dict:
    """{count, rental, add_ons, total} for the bookings made in [start, end]. Empty period: zeros."""
    rows = booked_value_rows(db, tenant_id, start, end, **filters)
    rental = sum(r["rental"] for r in rows)
    add_ons = sum(r["add_ons"] for r in rows)
    return {"count": len(rows), "rental": rental, "add_ons": add_ons, "total": rental + add_ons}


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
