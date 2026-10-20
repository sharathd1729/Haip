"""Business Overview (Owner Command Center): conversations -> leads -> bookings -> revenue on one page.

This module only COMPOSES. Every definition it uses already lives somewhere shared and is reused, not restated:
  * conversations, contacts, leads, qualified leads, cohort, conversion   lead_metrics   (the canonical LEAD definition)
  * enquiry records (repeat enquiries included)                           lead_metrics.enquiry_counts
  * bookings made                                                         kpi_metrics.booking_filters         (stays.booked)
  * cash in / refunds                                                     kpi_metrics.payment_totals          (payments.collected)
  * owed / paid / due                                                     booking_service.financials_for / schedules_for
  * work queue counts                                                     dashboard_service.needs_you_now     (-> work_queue_service)
  * integration health                                                    integration_health.classify
  * month target                                                          sales_performance_service.pickup_report
  * the owner dashboard (layout A, ``owner``)                             owner_dashboard_attention / owner_dashboard_blocks

A LEAD is a person HAIP holds a usable phone number for. A conversation or an enquiry is not a lead: one person who messages on
Instagram and WhatsApp and enquires twice is two conversations, two enquiries and ONE lead. The page keeps those apart and never
adds them up. Conversion is a cohort figure (see lead_metrics.lead_to_booking). docs/analytics/BUSINESS_OVERVIEW_IMPLEMENTATION.md
has the full rules; the ones this module keeps:
  * A figure the caller may not see is returned as ``None`` inside a block marked ``restricted``; it is never 0.
  * A figure HAIP cannot compute is ``{"available": False, "reason": ...}``; it is never 0.
  * A booking belongs to its guest (Stay.guest_id); source and agent splits follow the PERSON: first-touch channel and owner.
  * Reporting day is the IST calendar day (date_presets), shown to the user in the response.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad_metrics import AdMetric
from app.models.conversation import Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.stay_finance import StayAddOn
from app.services import booking_service, dashboard_service, integration_health, kpi_metrics, lead_metrics
from app.services import business_overview_extras as extras
from app.services import owner_dashboard_attention as owner_attention
from app.services import owner_dashboard_blocks as owner_blocks
from app.services import work_queue_service
from app.services.date_presets import IST, ist_range_to_utc
from app.services.business_overview_common import (  # noqa: F401  (Params, normalise_channel, previous_period are re-exported)
    Params, _change, _channel_condition, _lead_conditions, _linked_stay_ids, _money, _rate, _stay_conditions,
    normalise_channel, people_filters, previous_period,
)

LIVE_STATUSES = ("confirmed", "checked_in")
LIVE_STAY_CAP = 2000       # live bookings examined for "needs payment"; beyond this the answer says truncated
UPCOMING_DAYS = 7          # default window for upcoming check-ins; the request's window_days (3/7/15/30) replaces it
WINDOW_DAYS = (3, 7, 15, 30)

LEAD_DEFINITION = ("A lead is a person we hold a usable phone number for. A conversation, a DM or an enquiry on its own is not a lead; "
                   "one person across Instagram, WhatsApp and calls is one lead.")


# ── leads: people, kept apart from conversations and enquiries ───────────────────────────────────────────────

def _lead_numbers(db: Session, p: Params, start: str, end: str) -> dict:
    """The period's people-level numbers and the cohort of leads identified in it."""
    f = people_filters(p)
    return {**lead_metrics.cohort(db, p.tid, start, end, **f),
            "conversations": lead_metrics.count_conversations(db, p.tid, start, end, **f),
            "unidentified": lead_metrics.count_unidentified_contacts(db, p.tid, start, end, **f)}


def _funnel(cur: dict, prev: dict) -> dict:
    stages = [
        ("identified", "Lead identified", cur["identified"], prev["identified"], None),
        ("qualified", "Qualified", cur["qualified"], prev["qualified"], cur["identified"]),
        ("booked", "Booked", cur["booked"], prev["booked"], cur["identified"]),
        ("paid", "Payment collected", cur["paid"], prev["paid"], cur["booked"]),
    ]
    return {
        "basis": "cohort",
        "note": ("Counts the people who became leads (phone captured) in this period and what became of them so far. Each person is "
                 "counted once, however many chats, calls or enquiries they had. A lead can book or pay after the period ends, so "
                 "recent periods are still maturing. Qualified and Booked are measured against all identified leads; Payment "
                 "collected against those booked."),
        "stages": [{"key": k, "label": label, "count": n, "previous": pn,
                    "rate_from_previous": _rate(n, base) if base is not None else None,
                    "change": _change(n, pn)} for k, label, n, pn, base in stages],
    }


def _leads_block(db: Session, p: Params, cur: dict, prev: dict, queue: dict) -> dict:
    f = people_filters(p)
    active = lead_metrics.count_active_leads(db, p.tid, p.start, p.end, **f)
    enq = lead_metrics.enquiry_counts(db, p.tid, p.start, p.end, property_id=p.property_id, scope_user_id=p.scope_user_id,
                                      channel_condition=_channel_condition(p.channel) if p.channel else None)
    # Enquiries marked as spam are left out of the enquiry count; counted here so the page can say how many.
    spam_q = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == p.tid, Inquiry.qualification_status == kpi_metrics.UNQUALIFIED,
        Inquiry.created_at >= kpi_metrics.as_datetime(p.start), Inquiry.created_at <= kpi_metrics.as_datetime(p.end))
    if p.scope_user_id:
        spam_q = spam_q.filter(Inquiry.assigned_to == p.scope_user_id)
    if p.property_id:
        spam_q = spam_q.filter(Inquiry.property_id == p.property_id)
    if p.channel:
        spam_q = spam_q.filter(_channel_condition(p.channel))
    conversion = lead_metrics.lead_to_booking(cur)
    prev_rate = lead_metrics.lead_to_booking(prev)["rate"]
    return {
        "definition": LEAD_DEFINITION,
        "conversations_new": {"count": cur["conversations"], "change": _change(cur["conversations"], prev["conversations"]),
                              "basis": "conversations opened in the period; one person can have several"},
        "unidentified_contacts": {"count": cur["unidentified"], "change": _change(cur["unidentified"], prev["unidentified"]),
                                  "basis": "people who first got in touch in the period and still have no usable phone number"},
        "identified_new": {"count": cur["identified"], "change": _change(cur["identified"], prev["identified"]),
                           "basis": "unique people whose phone number was captured in the period (their first time as a lead)"},
        "identified_active": {"count": active,
                              "basis": "unique leads (phone known by the end of the period) with a message, call or enquiry in it"},
        "qualified_new": {"count": cur["qualified"], "change": _change(cur["qualified"], prev["qualified"]),
                          "rate_of_new": _rate(cur["qualified"], cur["identified"]),
                          "basis": "of the new leads, those with a non-spam enquiry in a valid pipeline stage, as of now"},
        "conversion": {**conversion, "previous_rate": prev_rate},
        "enquiries": {"created": enq["created"], "repeat": enq["repeat"], "change": None,
                      "marked_spam_excluded": spam_q.scalar() or 0, **extras.leads_extras(db, p),
                      "basis": "enquiry records created in the period; repeat enquiries from one person count each time"},
        "unassigned_now": queue["unassigned"],
    }


# ── bookings and revenue ─────────────────────────────────────────────────────────────────────────────────────

def _live_money(db: Session, p: Params, today: date) -> dict:
    """Bookings still to be paid: confirmed or checked-in stays that have not yet checked out."""
    q = db.query(Stay).filter(Stay.tenant_id == p.tid, Stay.status.in_(LIVE_STATUSES), Stay.check_out >= today)
    if p.property_id:
        q = q.filter(Stay.property_id == p.property_id)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        q = q.filter(Stay.id.in_(scoped))
    stays = q.order_by(Stay.check_in.asc()).limit(LIVE_STAY_CAP + 1).all()
    truncated = len(stays) > LIVE_STAY_CAP
    stays = stays[:LIVE_STAY_CAP]
    fins = booking_service.financials_for(db, p.tid, stays)
    schedules = booking_service.schedules_for(db, p.tid, fins)
    owing = [(s, fins[s.id]) for s in stays if fins[s.id]["outstanding"] > 0.005 and fins[s.id]["total"] > 0]
    overdue = 0
    overdue_amount = 0.0
    for s, fin in owing:
        due = booking_service.next_due(schedules.get(s.id, []))
        if due and due["overdue"]:
            overdue += 1
            overdue_amount += fin["outstanding"]
    return {"owing": len(owing), "overdue": overdue, "truncated": truncated,
            "outstanding_amount": sum(f["outstanding"] for _, f in owing),
            "overdue_amount": overdue_amount}


def _bookings_totals(db: Session, p: Params, start: str, end: str) -> dict:
    conds = _stay_conditions(p, start, end)
    count, value = db.query(func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0)).filter(*conds).one()
    cancelled = db.query(func.count(Stay.id)).filter(*_stay_conditions(p, start, end, statuses=("cancelled",))).scalar() or 0
    return {"count": int(count or 0), "value": float(value or 0), "cancelled": int(cancelled)}


def _bookings_and_revenue(db: Session, p: Params, today: date) -> tuple[dict, dict]:
    cur = _bookings_totals(db, p, p.start, p.end)
    prev = _bookings_totals(db, p, p.prev_start, p.prev_end)

    upcoming_from, upcoming_to = today, today + timedelta(days=p.window_days - 1)
    upcoming_q = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == p.tid, Stay.status == "confirmed",
        Stay.check_in >= upcoming_from, Stay.check_in <= upcoming_to)
    if p.property_id:
        upcoming_q = upcoming_q.filter(Stay.property_id == p.property_id)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        upcoming_q = upcoming_q.filter(Stay.id.in_(scoped))
    live = _live_money(db, p, today)

    split = lead_metrics.bookings_by_lead_cohort(db, p.tid, p.start, p.end, **people_filters(p))
    by_lead = {k: {"count": v["count"], "value": _money(p, v["value"])} for k, v in split.items()}
    narrowed = bool(p.scope_user_id or p.channel)
    if narrowed:        # a booking with no identified lead has no owner or channel, so it cannot be placed in a narrowed view
        by_lead["no_identified_lead"] = {"count": None, "value": None}

    bookings = {
        "restricted": False,
        "confirmed_created": cur["count"], "confirmed_change": _change(cur["count"], prev["count"]),
        "cancelled_of_created": cur["cancelled"],
        "pending": {"available": False, "reason": "HAIP bookings are confirmed, checked in, checked out or cancelled; there is no pending status."},
        "upcoming_checkins": int(upcoming_q.scalar() or 0), "upcoming_window_days": p.window_days,
        "needs_payment": live["owing"], "payment_overdue": live["overdue"], "needs_payment_truncated": live["truncated"],
        "by_lead_cohort": by_lead,
        "no_identified_lead": None if narrowed else split["no_identified_lead"]["count"],
        "basis": ("bookings created in the period (booked-on date), cancelled excluded; cancellations are those created in the period. "
                  "by_lead_cohort says whether they came from people who became leads in this period, from earlier leads, or from a guest with no phone number"),
    }

    day_from, day_to = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    scoped_ids = [Stay.id.in_(scoped)] if scoped is not None else []
    cash = kpi_metrics.payment_totals(db, p.tid, day_from, day_to, property_id=p.property_id, extra_filters=scoped_ids)
    prev_cash = kpi_metrics.payment_totals(db, p.tid, date.fromisoformat(p.prev_from), date.fromisoformat(p.prev_to),
                                           property_id=p.property_id, extra_filters=scoped_ids)
    addons = db.query(func.coalesce(func.sum(StayAddOn.quantity * StayAddOn.unit_price), 0)).join(
        Stay, Stay.id == StayAddOn.stay_id).filter(StayAddOn.tenant_id == p.tid, *_stay_conditions(p, p.start, p.end)).scalar()
    arriving = db.query(func.coalesce(func.sum(Stay.total_amount), 0)).filter(
        Stay.tenant_id == p.tid, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)),
        Stay.check_in >= day_from, Stay.check_in <= day_to,
        *([Stay.property_id == p.property_id] if p.property_id else []),
        *([Stay.id.in_(scoped)] if scoped is not None else [])).scalar()

    revenue = {
        "restricted": not p.can_revenue,
        "gross_booking_value": _money(p, cur["value"]), "gross_change": _change(cur["value"], prev["value"]) if p.can_revenue else None,
        "add_ons_value": _money(p, addons or 0),
        "arriving_value": _money(p, arriving or 0),
        "collected": _money(p, cash["collected"]), "collected_change": _change(cash["collected"], prev_cash["collected"]) if p.can_revenue else None,
        "refunds": _money(p, cash["refunded"]),
        "net_collected": _money(p, cash["net"]),
        "outstanding_on_live_bookings": _money(p, live["outstanding_amount"]),
        "overdue_amount": _money(p, live["overdue_amount"]),
        "net_revenue": {"available": False, "reason": "HAIP holds no tax, channel-commission or fee data, so a net revenue figure would be a guess."},
        "target": _target(db, p) if p.can_revenue else None,
        "basis": ("Gross booking value is the stay charge of bookings created in the period. Collected and refunds are "
                  "by payment date. Booked value, cash and arrivals are different measures and are never added together."),
    }
    return bookings, revenue


def _target(db: Session, p: Params) -> Optional[dict]:
    """The workspace's monthly pick-up target, only when the period sits inside one month and the view is workspace-wide."""
    if not p.tenant_wide or p.channel or p.property_id:
        return {"available": False, "reason": "Targets are set for the whole workspace; clear the filters to compare."}
    f, t = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    if (f.year, f.month) != (t.year, t.month):
        return {"available": False, "reason": "A target applies to one calendar month; pick a period inside one month."}
    from app.services import sales_performance_service
    rep = sales_performance_service.pickup_report(db, p.tid, f.replace(day=1))
    if not rep["has_target"]:
        return {"available": False, "reason": "No target is set for this month."}
    return {"available": True, "month": rep["month"], "monthly_target": rep["monthly_target"], "picked_up": rep["picked_up"],
            "achieved_pct": round(rep["achieved_pct"], 1) if rep["achieved_pct"] is not None else None,
            "basis": "month to date, bookings created in the month (the Targets page definition)"}


# ── enquiries by stage, sources, Meta Ads ────────────────────────────────────────────────────────────────────

def _pipeline(db: Session, p: Params) -> list[dict]:
    """Where this period's ENQUIRIES stand in the pipeline (records, so a repeat enquiry shows twice)."""
    rows = (db.query(PipelineStage.label, PipelineStage.category, PipelineStage.is_closed_won, PipelineStage.is_closed_lost,
                     PipelineStage.order, func.count(Inquiry.id))
            .join(Inquiry, Inquiry.stage_id == PipelineStage.id).filter(*_lead_conditions(p, p.start, p.end))
            .group_by(PipelineStage.id, PipelineStage.label, PipelineStage.category, PipelineStage.is_closed_won,
                      PipelineStage.is_closed_lost, PipelineStage.order).order_by(PipelineStage.order).all())
    return [{"stage": r[0], "category": r[1], "won": bool(r[2]), "lost": bool(r[3]), "count": r[5]} for r in rows]


def _source_rows(db: Session, p: Params) -> list[dict]:
    """New leads by FIRST-TOUCH channel (unique people). The channel they came back through later does not move them, and a
    person whose first touch is unknown is shown as Unknown."""
    rows = lead_metrics.by_first_touch(db, p.tid, p.start, p.end, with_bookings=p.can_bookings, **people_filters(p))
    return [{"key": r["key"], "label": r["label"], "leads": r["leads"],
             "bookings": r["bookings"] if p.can_bookings else None,
             "booking_value": _money(p, r["value"]) if p.can_bookings else None} for r in rows]


def _meta_ads(db: Session, p: Params) -> dict:
    """Meta Ads for the period: what Meta reports, and what HAIP can verify. Spend is Meta's own figure; leads and
    bookings count only when an ad referral was recorded against the conversation (LeadAttribution), and a lead is a person
    with a phone number."""
    row = db.query(Integration).filter_by(tenant_id=p.tid, kind="meta_ads").first()
    cfg = (row.config if row else None) or {}
    if not (row and cfg.get("ad_account_id")):
        return {"configured": False}
    f, t = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    spend, chats = db.query(func.coalesce(func.sum(AdMetric.spend), 0), func.coalesce(func.sum(AdMetric.conversations_started), 0)).filter(
        AdMetric.tenant_id == p.tid, AdMetric.date >= f, AdMetric.date <= t).one()
    start_dt, end_dt = ist_range_to_utc(p.d_from, p.d_to)[2:]
    atts = db.query(LeadAttribution).filter(LeadAttribution.tenant_id == p.tid, LeadAttribution.created_at >= start_dt,
                                            LeadAttribution.created_at <= end_dt).all()
    missing = [a.conversation_id for a in atts if not a.inquiry_id]
    via_conv = dict(db.query(Conversation.id, Conversation.inquiry_id).filter(
        Conversation.tenant_id == p.tid, Conversation.id.in_(missing))) if missing else {}
    inquiry_ids = {a.inquiry_id or via_conv.get(a.conversation_id) for a in atts} - {None}
    guest_ids = {g for (g,) in db.query(Inquiry.guest_id).filter(Inquiry.tenant_id == p.tid, Inquiry.id.in_(inquiry_ids))} if inquiry_ids else set()
    identified = (db.query(func.count(Guest.id)).filter(Guest.tenant_id == p.tid, Guest.id.in_(guest_ids), Guest.is_deleted.is_(False),
                                                        Guest.lead_identified_at.isnot(None)).scalar() or 0) if guest_ids else 0
    bookings, value = 0, 0.0
    if guest_ids and p.can_bookings:
        bookings, value = db.query(func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0)).filter(
            Stay.tenant_id == p.tid, Stay.guest_id.in_(guest_ids), Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES))).one()
    chats = int(chats or 0)
    return {
        "configured": True, "last_synced_at": cfg.get("last_synced_at"), "last_error": cfg.get("last_error"),
        "spend": _money(p, float(spend or 0)),
        "reported_chats": chats,                                  # platform-reported
        "verified_conversations": len({a.conversation_id for a in atts}),   # HAIP-recorded referrals
        "verified_contacts": len(guest_ids),                     # people behind those conversations
        "verified_leads": int(identified),                       # of them, people with a phone number
        "verified_bookings": int(bookings or 0) if p.can_bookings else None,
        "verified_booking_value": _money(p, float(value or 0)) if p.can_bookings else None,
        "cost_per_verified_lead": _money(p, float(spend) / identified) if identified and spend else None,
        "return_on_spend": round(float(value or 0) / float(spend), 2) if p.can_revenue and p.can_bookings and spend else None,
        "not_traced": max(0, chats - len({a.conversation_id for a in atts})),
        "basis": "Spend and chats are Meta's figures. Leads and bookings count only chats where HAIP recorded the ad referral; a lead is "
                 "a person from those chats whose phone number we hold; bookings are those made by those people (any time since).",
    }


# ── attention and freshness ──────────────────────────────────────────────────────────────────────────────────

def _meta_with_detail(db: Session, p: Params) -> dict:
    meta = _meta_ads(db, p)
    return {**meta, **extras.meta_detail(db, p)} if meta.get("configured") else meta


def _people_in(work: dict, kinds: tuple[str, ...], total: int) -> Optional[int]:
    """How many different people the queue items of these kinds are about, or None when the list was cut short."""
    items = [i for i in work.get("items", []) if i["kind"] in kinds]
    if len(items) < total:
        return None
    return len({i.get("guest_id") or i.get("title") for i in items})


def _attention(q: dict, bookings: Optional[dict], at_risk: dict, work: dict) -> list[dict]:
    """Actionable WORKLOAD: each row counts the people to contact (new leads, missed calls, leads waiting) and the follow-ups and
    bookings to deal with. ``people`` is how many different people they are about, when that is known. Nothing is hidden: an overdue follow-up, a
    missed call or an unpaid booking always shows."""
    items = [
        ("new_leads", "New leads nobody has contacted", q["new_leads"], q["new_leads_oldest_at"], "/dashboard/my-day?kind=new_lead", ("new_lead",)),
        ("missed_calls", "Missed calls not called back", q["missed_not_called_back"], q["missed_oldest_at"], "/dashboard/my-day?kind=callback", ("callback",)),
        ("waiting_reply", "Leads waiting for a reply", q["waiting_reply"], q["waiting_oldest_at"], "/dashboard/my-day?kind=reply", ("reply",)),
        ("followups", "Follow-ups overdue", q["followups_overdue"], q["followups_oldest_due"], "/dashboard/my-day?kind=followup", ("followup",)),
    ]
    out = [{"key": k, "label": label, "count": n, "oldest_at": oldest, "href": href, "people": _people_in(work, kinds, n)}
           for k, label, n, oldest, href, kinds in items]
    if at_risk["count"]:
        out.append({"key": "high_intent_risk", "label": "Promising enquiries at risk", "count": at_risk["count"], "oldest_at": None,
                    "href": "/dashboard/leads", "people": at_risk["count"]})
    if bookings and not bookings.get("restricted"):
        out += [{"key": "payment_overdue", "label": "Bookings with an overdue payment", "count": bookings["payment_overdue"],
                 "oldest_at": None, "href": "/dashboard/bookings", "people": None},
                {"key": "needs_payment", "label": "Upcoming bookings still owing money", "count": bookings["needs_payment"],
                 "oldest_at": None, "href": "/dashboard/bookings", "people": None}]
    return out


def _integrations(db: Session, p: Params) -> list[dict]:
    out = []
    for row in db.query(Integration).filter(Integration.tenant_id == p.tid).all():
        health = integration_health.classify(row.kind, row.status, row.last_health_at, config=row.config)
        if health in (integration_health.YELLOW, integration_health.RED):
            cfg = row.config or {}
            out.append({"kind": row.kind, "label": integration_health.label(row.kind), "status": health,
                        "last_sync": row.last_health_at or cfg.get("last_synced_at"),
                        "message": cfg.get("last_error"), "href": "/dashboard/settings/integrations"})
    return out


# ── entry point ──────────────────────────────────────────────────────────────────────────────────────────────

def build(db: Session, p: Params, tenant) -> dict:
    today = datetime.now(IST).date()
    cur, prev = _lead_numbers(db, p, p.start, p.end), _lead_numbers(db, p, p.prev_start, p.prev_end)
    work = work_queue_service.build(db, tenant, p.scope_user_id)             # the shared work queue, read once
    queue = dashboard_service.needs_you_now_from(work)
    at_risk = extras.high_intent_at_risk(db, p, work)

    computed_bookings = computed_revenue = None
    if p.can_bookings or p.can_revenue:
        computed_bookings, computed_revenue = _bookings_and_revenue(db, p, today)
    # A block the viewer may not see is replaced whole by a restricted marker (never zeros).
    bookings = computed_bookings if p.can_bookings else {"restricted": True}
    revenue = computed_revenue if p.can_revenue else {"restricted": True}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"date_from": p.d_from, "date_to": p.d_to, "timezone": "Asia/Kolkata",
                   "previous_from": p.prev_from, "previous_to": p.prev_to},
        "filters": {"property_id": p.property_id, "channel": p.channel, "agent_id": p.scope_user_id if p.tenant_wide else None},
        "access": {"tenant_wide": p.tenant_wide, "bookings": p.can_bookings, "revenue": p.can_revenue},
        "leads": {**_leads_block(db, p, cur, prev, queue), "high_intent_at_risk": at_risk},
        "bookings": bookings if bookings.get("restricted") else {**bookings, **extras.bookings_extras(db, p, today)},
        "revenue": revenue,
        "funnel": _funnel(cur, prev),
        "series": extras.trend_series(db, p),
        "pipeline": _pipeline(db, p),
        "sources": _source_rows(db, p),
        "meta_ads": _meta_with_detail(db, p) if p.tenant_wide else None,
        "agents": extras.agent_table(db, p),
        "attention": _attention(queue, bookings, at_risk, work),
        "stale_integrations": _integrations(db, p) if p.tenant_wide else [],
        "insights": dashboard_service.top_insights(db, p.tid) if p.tenant_wide else [],
        "owner": _owner(db, p, work, today),
    }


def _owner(db: Session, p: Params, work: dict, today: date) -> dict:
    """The owner dashboard, layout A (19 Oct 2026). Built from the same work-queue read as ``attention``."""
    return {
        "attention": owner_attention.attention_cards(work, owner_attention.owing_card(db, p, today) if p.can_bookings else None),
        "kpis": owner_blocks.kpis(db, p),
        "target": owner_blocks.target(db, p, today),
        "movements": owner_attention.movements(db, p, today, p.window_days) if p.can_bookings else {"restricted": True},
        "travel": owner_blocks.travel(db, p, today),
        "stages": owner_blocks.stages(db, p),
        "caravans": owner_blocks.caravans(db, p, today),
        "ai_calls": owner_blocks.ai_calls(db, p),
        "team": owner_blocks.team(db, p, today),
        "today": today.isoformat(),
    }
