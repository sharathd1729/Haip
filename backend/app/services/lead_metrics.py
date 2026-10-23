"""Canonical lead metrics (docs/analytics/KPI_METRIC_CATALOGUE.md, "Lead definition").

THE definition: a LEAD is an identifiable person (a Guest) for whom HAIP has captured a usable phone number, directly or through a
reliable identity match. ``Guest.lead_identified_at`` records the moment that first became true (identity_resolution). An
Instagram DM with no number is a conversation and a contact, not a lead. Six things are counted separately and never added up:

  conversations.new      conversations opened in the period (interactions; a person can have several)
  contacts.unidentified  people who first got in touch in the period and have no usable phone number yet
  leads.identified_new   unique people who BECAME leads in the period (identification date)
  leads.identified_active  unique leads who did something in the period (a message, a call or an enquiry)
  leads.qualified_new    of the new leads, those with an enquiry that is not spam and sits in a "valid" pipeline stage
  leads.qualified_dated  of the new leads, those with a non-spam enquiry that carries a check-in date (D-22..D-24, 19 Oct 2026)
  enquiries.created      enquiry records created in the period (repeat enquiries from one person count each time)

Bookings and cash are the existing kpi_metrics (stays.booked, payments.collected). Conversion is a COHORT figure: of the leads
identified in the period, the share that has booked so far. It is never "bookings today / leads today".

Every function is tenant-first, takes explicit period bounds (IST days converted to UTC by the caller) and never returns None for an
empty period. The optional filters narrow the PEOPLE counted: ``property_id`` (an enquiry, conversation or booking for it),
``channel`` (first-touch channel), ``scope_user_id`` (the lead's owner: the assignee of their latest enquiry, else of their latest
conversation).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import and_, case, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.call import Call
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.stay_finance import StayPayment
from app.services.kpi_metrics import OCCUPYING_STATUSES, UNQUALIFIED, Bound, as_datetime
from app.services.lead_state import CHANNEL_BY_SOURCE
from app.services.lead_types import is_guest_sql

CHANNEL_LABELS = {"whatsapp": "WhatsApp", "instagram": "Instagram", "facebook": "Facebook", "call": "Phone calls",
                  "organic_call": "Organic calls", "website": "Website", "other": "Other", "unknown": "Unknown"}
_SOURCE_VALUES = {s.value for s in InquirySource}

# A conversation's channel -> the channel key the dashboard filters by.
CONVERSATION_CHANNEL_KEY = {
    ChannelType.WHATSAPP: "whatsapp", ChannelType.INSTAGRAM: "instagram", ChannelType.VOICE: "call",
    ChannelType.WEBCHAT: "website", ChannelType.EMAIL: "other",
}


# ── who is counted ───────────────────────────────────────────────────────────────────────────────────────────

def _owner_expr(tenant_id: str):
    """The lead's owner: assignee of their latest enquiry, else of their latest conversation."""
    latest_inquiry = (select(Inquiry.assigned_to).where(Inquiry.guest_id == Guest.id, Inquiry.tenant_id == tenant_id)
                      .order_by(Inquiry.created_at.desc()).limit(1).correlate(Guest).scalar_subquery())
    latest_conversation = (select(Conversation.assigned_to).where(Conversation.guest_id == Guest.id, Conversation.tenant_id == tenant_id)
                           .order_by(Conversation.created_at.desc()).limit(1).correlate(Guest).scalar_subquery())
    return func.coalesce(latest_inquiry, latest_conversation)


def first_touch_expr(tenant_id: str):
    """The person's first-touch channel as the dashboard shows it. ``Guest.first_touch_channel`` (written once, never guessed) wins,
    except that a first touch by phone whose first enquiry is an ``organic_call`` (an inbound call with no ad behind it) is shown as
    "organic_call". With no first touch recorded, the source of the person's FIRST enquiry decides (lead_state.CHANNEL_BY_SOURCE),
    so an organic-call lead is never "unknown"; with neither it stays "unknown"."""
    i = aliased(Inquiry)
    first_source = (select(i.source).where(i.guest_id == Guest.id, i.tenant_id == tenant_id)
                    .order_by(i.created_at.asc()).limit(1).correlate(Guest).scalar_subquery())
    by_source = [(first_source == InquirySource(raw), literal(channel)) for raw, channel in CHANNEL_BY_SOURCE.items()
                 if raw in _SOURCE_VALUES]
    return case(
        (and_(Guest.first_touch_channel == "call", first_source == InquirySource.ORGANIC_CALL), literal("organic_call")),
        (Guest.first_touch_channel.isnot(None), Guest.first_touch_channel),
        *by_source,
        else_=literal("unknown"))


def people(tenant_id: str, *, property_id: Optional[str] = None, channel: Optional[str] = None,
           scope_user_id: Optional[str] = None) -> list:
    """Conditions selecting the people a metric may count. Merged, erased and sample guests are never counted. The channel filter
    reads ``first_touch_expr``; "call" keeps its organic calls (they are calls too), "organic_call" is only those."""
    conds = [Guest.tenant_id == tenant_id, Guest.is_deleted.is_(False), Guest.is_sample.is_(False), _guest_type(tenant_id)]
    if channel:
        touch = first_touch_expr(tenant_id)
        conds.append(touch.in_(["call", "organic_call"]) if channel == "call" else touch == channel)
    if scope_user_id:
        conds.append(_owner_expr(tenant_id) == scope_user_id)
    if property_id:
        # Aliases, so these correlated subqueries never swallow the outer query's own Inquiry / Conversation / Stay.
        i, c, st = aliased(Inquiry), aliased(Conversation), aliased(Stay)
        conds.append(or_(
            exists().where(i.guest_id == Guest.id, i.tenant_id == tenant_id, i.property_id == property_id),
            exists().where(c.guest_id == Guest.id, c.tenant_id == tenant_id, c.property_id == property_id),
            exists().where(st.guest_id == Guest.id, st.tenant_id == tenant_id, st.property_id == property_id)))
    return conds


def _guest_type(tenant_id: str):
    """Guest lead KPIs count guests (lead_types): a person is left out only when they have enquiries and EVERY one of them is
    b2b / partner. A person with no enquiry yet is still counted."""
    other, guest = aliased(Inquiry), aliased(Inquiry)
    return or_(~exists().where(other.guest_id == Guest.id, other.tenant_id == tenant_id, ~is_guest_sql(other.lead_type)),
               exists().where(guest.guest_id == Guest.id, guest.tenant_id == tenant_id, is_guest_sql(guest.lead_type)))


def _between(column, start: Bound, end: Bound) -> list:
    return [column >= as_datetime(start), column <= as_datetime(end)]


def _count(db: Session, conds: list) -> int:
    return int(db.query(func.count(Guest.id)).filter(*conds).scalar() or 0)


# ── the metrics ──────────────────────────────────────────────────────────────────────────────────────────────

def new_leads_conditions(tenant_id: str, start: Bound, end: Bound, **filters) -> list:
    return [*people(tenant_id, **filters), Guest.lead_identified_at.isnot(None), *_between(Guest.lead_identified_at, start, end)]


def count_new_leads(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> int:
    """leads.identified_new: unique people whose phone number was captured in the period."""
    return _count(db, new_leads_conditions(tenant_id, start, end, **filters))


def count_unidentified_contacts(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> int:
    """contacts.unidentified: people first heard from in the period who still have no usable phone number."""
    return _count(db, [*people(tenant_id, **filters), Guest.lead_identified_at.is_(None), *_between(Guest.created_at, start, end)])


def _conversation_query(db: Session, columns, tenant_id: str, start: Bound, end: Bound, *, property_id: Optional[str],
                        channel: Optional[str], scope_user_id: Optional[str]):
    q = (db.query(*columns).join(Guest, Guest.id == Conversation.guest_id)
         .filter(Conversation.tenant_id == tenant_id, Guest.tenant_id == tenant_id, Guest.is_deleted.is_(False),
                 Guest.is_sample.is_(False), Conversation.channel != ChannelType.INTERNAL,
                 *_between(Conversation.created_at, start, end)))
    if property_id:
        q = q.filter(Conversation.property_id == property_id)
    if scope_user_id:
        q = q.filter(Conversation.assigned_to == scope_user_id)
    if channel:
        q = q.filter(Conversation.channel.in_([c for c, key in CONVERSATION_CHANNEL_KEY.items() if key == channel]))
    return q


def count_conversations(db: Session, tenant_id: str, start: Bound, end: Bound, *, property_id: Optional[str] = None,
                        channel: Optional[str] = None, scope_user_id: Optional[str] = None) -> int:
    """conversations.new: conversations opened in the period (internal notes threads excluded)."""
    q = _conversation_query(db, [func.count(Conversation.id)], tenant_id, start, end, property_id=property_id,
                            channel=channel, scope_user_id=scope_user_id)
    return int(q.scalar() or 0)


def conversation_times(db: Session, tenant_id: str, start: Bound, end: Bound, *, property_id: Optional[str] = None,
                       channel: Optional[str] = None, scope_user_id: Optional[str] = None) -> list:
    """When each conversation in the period was opened (for the trend chart)."""
    q = _conversation_query(db, [Conversation.created_at], tenant_id, start, end, property_id=property_id,
                            channel=channel, scope_user_id=scope_user_id)
    return [row[0] for row in q.all()]


def _qualified_conditions(tenant_id: str) -> list:
    """The ONE "qualified enquiry" rule: not marked spam and in a valid pipeline stage (as of now)."""
    return [Inquiry.tenant_id == tenant_id, Inquiry.qualification_status != UNQUALIFIED,
            Inquiry.stage_id == PipelineStage.id, PipelineStage.category == "valid"]


def _qualified_exists(tenant_id: str):
    return exists().where(Inquiry.guest_id == Guest.id, *_qualified_conditions(tenant_id))


def qualified_inquiry_ids(db: Session, tenant_id: str, inquiry_ids) -> set[str]:
    """Of these enquiries, the qualified ones (same rule as leads.qualified_new); used by the marketing money funnel."""
    ids = list({i for i in inquiry_ids if i})
    if not ids:
        return set()
    return {i for (i,) in db.query(Inquiry.id).filter(Inquiry.id.in_(ids), *_qualified_conditions(tenant_id))}


def count_qualified_new(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> int:
    """leads.qualified_new: of the new leads, those with a non-spam enquiry in a valid pipeline stage (as of now)."""
    return _count(db, [*new_leads_conditions(tenant_id, start, end, **filters), _qualified_exists(tenant_id)])


def _dated_exists(tenant_id: str):
    """A non-spam enquiry of the person that carries a check-in date (any stage)."""
    i = aliased(Inquiry)
    return exists().where(i.guest_id == Guest.id, i.tenant_id == tenant_id, i.qualification_status != UNQUALIFIED,
                          i.check_in.isnot(None), i.check_in != "")


def count_qualified_dated(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> int:
    """leads.qualified_dated: of the new leads, those with a non-spam enquiry carrying a check-in date (phone + travel date)."""
    return _count(db, [*new_leads_conditions(tenant_id, start, end, **filters), _dated_exists(tenant_id)])


def count_active_leads(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> int:
    """leads.identified_active: unique identified leads with a message, a call or a new enquiry in the period."""
    s, e = as_datetime(start), as_datetime(end)
    active = or_(
        exists().where(Inquiry.guest_id == Guest.id, Inquiry.tenant_id == tenant_id, Inquiry.created_at >= s, Inquiry.created_at <= e),
        exists().where(Call.guest_id == Guest.id, Call.tenant_id == tenant_id, Call.created_at >= s, Call.created_at <= e),
        exists().where(Conversation.guest_id == Guest.id, Conversation.tenant_id == tenant_id,
                       Message.conversation_id == Conversation.id, Message.tenant_id == tenant_id,
                       Message.created_at >= s, Message.created_at <= e))
    return _count(db, [*people(tenant_id, **filters), Guest.lead_identified_at.isnot(None), Guest.lead_identified_at <= e, active])


def enquiry_counts(db: Session, tenant_id: str, start: Bound, end: Bound, *, property_id: Optional[str] = None,
                   scope_user_id: Optional[str] = None, channel_condition=None) -> dict:
    """enquiries.created: enquiry records created in the period, and how many were repeat enquiries (the same person had an
    earlier one). One person with three enquiries is three enquiries and ONE lead."""
    conds = [Inquiry.tenant_id == tenant_id, *_between(Inquiry.created_at, start, end), Inquiry.qualification_status != UNQUALIFIED,
             is_guest_sql(Inquiry.lead_type)]
    if scope_user_id:
        conds.append(Inquiry.assigned_to == scope_user_id)
    if property_id:
        conds.append(Inquiry.property_id == property_id)
    if channel_condition is not None:
        conds.append(channel_condition)
    created = int(db.query(func.count(Inquiry.id)).filter(*conds).scalar() or 0)
    prior = aliased(Inquiry)
    repeat = int(db.query(func.count(Inquiry.id)).filter(
        *conds, exists().where(prior.guest_id == Inquiry.guest_id, prior.tenant_id == tenant_id, prior.created_at < Inquiry.created_at)
    ).scalar() or 0)
    return {"created": created, "repeat": repeat}


# ── cohort: what became of the people identified in the period ───────────────────────────────────────────────

def _booked_exists(tenant_id: str):
    return exists().where(Stay.guest_id == Guest.id, Stay.tenant_id == tenant_id, Stay.status.in_(list(OCCUPYING_STATUSES)))


def _paid_exists(tenant_id: str):
    net_paid = (select(StayPayment.stay_id).where(StayPayment.tenant_id == tenant_id).group_by(StayPayment.stay_id)
                .having(func.sum(case((StayPayment.kind == "refund", -StayPayment.amount), else_=StayPayment.amount)) > 0))
    return exists().where(Stay.guest_id == Guest.id, Stay.tenant_id == tenant_id,
                          Stay.status.in_(list(OCCUPYING_STATUSES)), Stay.id.in_(net_paid))


def cohort(db: Session, tenant_id: str, start: Bound, end: Bound, **filters) -> dict:
    """The leads identified in [start, end] and what became of them SO FAR. A lead can book after the period ends, so recent
    periods are still maturing. ``booked`` is a person with at least one live booking (any time), not a count of bookings."""
    base = new_leads_conditions(tenant_id, start, end, **filters)
    return {
        "identified": _count(db, base),
        "qualified": _count(db, [*base, _qualified_exists(tenant_id)]),
        "booked": _count(db, [*base, _booked_exists(tenant_id)]),
        "paid": _count(db, [*base, _paid_exists(tenant_id)]),
    }


def bookings_by_lead_cohort(db: Session, tenant_id: str, start: Bound, end: Bound, *, property_id: Optional[str] = None,
                            channel: Optional[str] = None, scope_user_id: Optional[str] = None) -> dict:
    """Bookings made in the period, split by WHEN their guest became a lead, so "bookings today" is never read as coming from
    "leads today": from leads identified in the period, from leads identified earlier, from a guest with no number yet."""
    s = as_datetime(start)
    conds = [Stay.tenant_id == tenant_id, *_between(Stay.created_at, start, end), Stay.status.in_(list(OCCUPYING_STATUSES)),
             *people(tenant_id, channel=channel, scope_user_id=scope_user_id)]
    if property_id:
        conds.append(Stay.property_id == property_id)
    out = {"from_new_leads": [0, 0.0], "from_earlier_leads": [0, 0.0], "no_identified_lead": [0, 0.0]}
    for identified, amount in db.query(Guest.lead_identified_at, Stay.total_amount).select_from(Stay).join(Guest, Guest.id == Stay.guest_id).filter(*conds).all():
        if identified is None:
            slot = out["no_identified_lead"]
        elif as_datetime(identified) >= s:
            slot = out["from_new_leads"]
        else:
            slot = out["from_earlier_leads"]
        slot[0] += 1
        slot[1] += float(amount or 0)
    return {k: {"count": v[0], "value": v[1]} for k, v in out.items()}


def lead_to_booking(cohort_counts: dict) -> dict:
    """Conversion, with its numerator and denominator spelled out: leads identified in the period that have booked so far."""
    n, d = cohort_counts["booked"], cohort_counts["identified"]
    return {"numerator": n, "denominator": d, "rate": round(n / d * 100, 1) if d else None,
            "basis": "cohort: of the people who became leads in this period, the share that has a booking so far"}


# ── breakdowns of the new leads ──────────────────────────────────────────────────────────────────────────────

def by_first_touch(db: Session, tenant_id: str, start: Bound, end: Bound, *, with_bookings: bool, **filters) -> list[dict]:
    """New leads (unique people) by first-touch channel (``first_touch_expr``). An unknown first touch is its own row, never folded
    into another. Counted in Python, not GROUP BY: the channel expression carries bound parameters, which PostgreSQL will not match
    between SELECT and GROUP BY."""
    base = new_leads_conditions(tenant_id, start, end, **filters)
    rows: dict[str, dict] = defaultdict(lambda: {"leads": 0, "bookings": 0, "value": 0.0})
    channel = first_touch_expr(tenant_id)
    for (key,) in db.query(channel).filter(*base).all():
        rows[key or "unknown"]["leads"] += 1
    if with_bookings:
        for key, amount in (db.query(channel, Stay.total_amount).select_from(Guest).join(Stay, Stay.guest_id == Guest.id)
                            .filter(*base, Stay.tenant_id == tenant_id, Stay.status.in_(list(OCCUPYING_STATUSES))).all()):
            rows[key or "unknown"]["bookings"] += 1
            rows[key or "unknown"]["value"] += float(amount or 0)
    return [{"key": k, "label": CHANNEL_LABELS.get(k, k.title()), **v} for k, v in sorted(rows.items(), key=lambda kv: -kv[1]["leads"])]


def by_owner(db: Session, tenant_id: str, start: Bound, end: Bound, *, with_bookings: bool, **filters) -> dict:
    """New leads per owner: {owner_id or None: {leads, qualified, bookings, value}} (unique people, each counted once)."""
    base = new_leads_conditions(tenant_id, start, end, **filters)
    out: dict = defaultdict(lambda: {"leads": 0, "qualified": 0, "bookings": 0, "value": 0.0})
    owner = _owner_expr(tenant_id)
    for gid, uid, qualified in db.query(Guest.id, owner, _qualified_exists(tenant_id)).filter(*base).all():
        out[uid]["leads"] += 1
        out[uid]["qualified"] += 1 if qualified else 0
    if with_bookings:
        for uid, n, v in (db.query(owner, func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0))
                          .select_from(Guest).join(Stay, Stay.guest_id == Guest.id)
                          .filter(*base, Stay.tenant_id == tenant_id, Stay.status.in_(list(OCCUPYING_STATUSES)))
                          .group_by(owner).all()):
            out[uid]["bookings"] += int(n)
            out[uid]["value"] += float(v or 0)
    return out
