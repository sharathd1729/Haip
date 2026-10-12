"""Business Overview (Owner Command Center): leads -> bookings -> revenue on one page.

This module only COMPOSES. Every definition it uses already lives somewhere shared and is reused, not restated:
  * new leads            kpi_metrics.lead_filters            (leads.new)
  * bookings made        kpi_metrics.booking_filters         (stays.booked)
  * cash in / refunds    kpi_metrics.payment_totals          (payments.collected)
  * owed / paid / due    booking_service.financials_for / schedules_for
  * work queue counts    dashboard_service.needs_you_now     (-> work_queue_service)
  * integration health   integration_health.classify
  * month target         sales_performance_service.pickup_report
The one thing computed here is how they fit together: the lead -> booking -> payment cohort and the per-source /
per-agent splits that join leads to the bookings linked to them (Stay.inquiry_id).

Rules this module keeps (docs/analytics/BUSINESS_OVERVIEW_IMPLEMENTATION.md has the full list):
  * A figure the caller may not see is returned as ``None`` inside a block marked ``restricted``; it is never 0.
  * A figure HAIP cannot compute is ``{"available": False, "reason": ...}``; it is never 0.
  * Only a booking with a lead link (Stay.inquiry_id) is attributed to a source or an agent. The rest are counted
    as "not linked to a lead" and shown as such.
  * Reporting day is the IST calendar day (date_presets), shown to the user in the response.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.ad_metrics import AdMetric
from app.models.conversation import Conversation
from app.models.inquiry import Inquiry
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.stay_finance import StayAddOn, StayPayment
from app.models.user import User
from app.services import booking_service, dashboard_service, integration_health, kpi_metrics
from app.services.date_presets import IST, ist_range_to_utc
from app.services.business_overview_common import (  # noqa: F401  (Params, normalise_channel, previous_period are re-exported)
    Params, _change, _channel_condition, _ist_day, _lead_conditions, _linked_stay_ids, _money, _rate, _stay_conditions,
    normalise_channel, previous_period,
)

LIVE_STATUSES = ("confirmed", "checked_in")
LIVE_STAY_CAP = 2000       # live bookings examined for "needs payment"; beyond this the answer says truncated
UPCOMING_DAYS = 7


# ── leads and the lead -> booking -> payment cohort ──────────────────────────────────────────────────────────

def _cohort(db: Session, p: Params, start: str, end: str) -> dict:
    """Leads received in the period and what became of them SO FAR (a lead may book after the period closes)."""
    conds = _lead_conditions(p, start, end)
    received = db.query(func.count(Inquiry.id)).filter(*conds).scalar() or 0

    by_cat = dict(db.query(PipelineStage.category, func.count(Inquiry.id))
                  .join(PipelineStage, PipelineStage.id == Inquiry.stage_id).filter(*conds)
                  .group_by(PipelineStage.category).all())
    valid, invalid = by_cat.get("valid", 0), by_cat.get("invalid", 0)

    booked_q = (db.query(func.count(func.distinct(Inquiry.id)))
                .join(Stay, Stay.inquiry_id == Inquiry.id)
                .filter(*conds, Stay.tenant_id == p.tid, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES))))
    booked_any = booked_q.scalar() or 0
    booked_valid = (booked_q.join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
                    .filter(PipelineStage.category == "valid").scalar() or 0)

    paid_sq = (db.query(StayPayment.stay_id.label("stay_id"),
                        func.sum(case((StayPayment.kind == "refund", -StayPayment.amount), else_=StayPayment.amount)).label("net"))
               .filter(StayPayment.tenant_id == p.tid).group_by(StayPayment.stay_id).subquery())
    paid = (db.query(func.count(func.distinct(Inquiry.id)))
            .join(Stay, Stay.inquiry_id == Inquiry.id).join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
            .join(paid_sq, paid_sq.c.stay_id == Stay.id)
            .filter(*conds, Stay.tenant_id == p.tid, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)),
                    PipelineStage.category == "valid", paid_sq.c.net > 0).scalar() or 0)
    return {"received": received, "valid": valid, "invalid": invalid, "booked_any": booked_any,
            "booked_valid": booked_valid, "paid": paid}


def _funnel(cur: dict, prev: dict) -> dict:
    stages = [
        ("received", "Lead received", cur["received"], prev["received"], None),
        ("valid", "Valid lead", cur["valid"], prev["valid"], cur["received"]),
        ("booked", "Booking confirmed", cur["booked_valid"], prev["booked_valid"], cur["valid"]),
        ("paid", "Payment collected", cur["paid"], prev["paid"], cur["booked_valid"]),
    ]
    return {
        "basis": "cohort",
        "note": ("Counts the leads received in this period and what became of them so far. A lead can book or pay "
                 "after the period ends, so recent periods are still maturing. Only bookings linked to a lead are counted."),
        "stages": [{"key": k, "label": label, "count": n, "previous": pn,
                    "rate_from_previous": _rate(n, base) if base is not None else None,
                    "change": _change(n, pn)} for k, label, n, pn, base in stages],
    }


def _leads_block(db: Session, p: Params, cur: dict, prev: dict, queue: dict) -> dict:
    # Enquiries marked as spam are left out of "received" (leads.new); counted here so the page can say how many.
    spam_q = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == p.tid, Inquiry.qualification_status == kpi_metrics.UNQUALIFIED,
        Inquiry.created_at >= kpi_metrics.as_datetime(p.start), Inquiry.created_at <= kpi_metrics.as_datetime(p.end))
    if p.scope_user_id:
        spam_q = spam_q.filter(Inquiry.assigned_to == p.scope_user_id)
    if p.property_id:
        spam_q = spam_q.filter(Inquiry.property_id == p.property_id)
    if p.channel:
        spam_q = spam_q.filter(_channel_condition(p.channel))
    spam = spam_q.scalar() or 0
    return {
        "received": cur["received"], "received_change": _change(cur["received"], prev["received"]),
        "valid": cur["valid"], "invalid": cur["invalid"],
        "marked_spam_excluded": spam,
        "converted_to_booking": cur["booked_any"],
        "conversion_rate": _rate(cur["booked_any"], cur["received"]),
        "conversion_basis": "cohort: leads received in the period that have a linked booking so far",
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

    upcoming_from, upcoming_to = today, today + timedelta(days=UPCOMING_DAYS - 1)
    upcoming_q = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == p.tid, Stay.status == "confirmed",
        Stay.check_in >= upcoming_from, Stay.check_in <= upcoming_to)
    if p.property_id:
        upcoming_q = upcoming_q.filter(Stay.property_id == p.property_id)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        upcoming_q = upcoming_q.filter(Stay.id.in_(scoped))
    live = _live_money(db, p, today)

    unlinked = None
    if p.tenant_wide and not p.channel and p.scope_user_id is None:
        unlinked = db.query(func.count(Stay.id)).filter(
            *kpi_metrics.booking_filters(p.tid, p.start, p.end, property_id=p.property_id), Stay.inquiry_id.is_(None)).scalar() or 0

    bookings = {
        "restricted": False,
        "confirmed_created": cur["count"], "confirmed_change": _change(cur["count"], prev["count"]),
        "cancelled_of_created": cur["cancelled"],
        "pending": {"available": False, "reason": "HAIP bookings are confirmed, checked in, checked out or cancelled; there is no pending status."},
        "upcoming_checkins": int(upcoming_q.scalar() or 0), "upcoming_window_days": UPCOMING_DAYS,
        "needs_payment": live["owing"], "payment_overdue": live["overdue"], "needs_payment_truncated": live["truncated"],
        "not_linked_to_a_lead": unlinked,
        "basis": "bookings created in the period (booked-on date), cancelled excluded; cancellations are those created in the period",
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


# ── trends ───────────────────────────────────────────────────────────────────────────────────────────────────

def _series(db: Session, p: Params) -> dict:
    d_from, d_to = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    days = dashboard_service._day_list(d_from, d_to)
    start, end = dashboard_service._utc_bounds(days)
    leads, booked, value = defaultdict(int), defaultdict(int), defaultdict(float)
    for (created,) in db.query(Inquiry.created_at).filter(*_lead_conditions(p, start, end)).all():
        leads[_ist_day(created)] += 1
    if p.can_bookings:
        for created, amount in db.query(Stay.created_at, Stay.total_amount).filter(*_stay_conditions(p, start, end)).all():
            booked[_ist_day(created)] += 1
            value[_ist_day(created)] += float(amount or 0)
    cash = defaultdict(float)
    if p.can_revenue:
        q = (db.query(StayPayment.paid_on, StayPayment.kind, StayPayment.amount).join(Stay, Stay.id == StayPayment.stay_id)
             .filter(StayPayment.tenant_id == p.tid, StayPayment.paid_on >= days[0], StayPayment.paid_on <= days[-1]))
        if p.property_id:
            q = q.filter(Stay.property_id == p.property_id)
        scoped = _linked_stay_ids(p)
        if scoped is not None:
            q = q.filter(Stay.id.in_(scoped))
        for paid_on, kind, amount in q.all():
            cash[paid_on] += float(amount) * (-1 if kind == "refund" else 1)
    return {
        "days": [d.isoformat() for d in days],
        "period_start_index": max(0, days.index(d_from)) if d_from in days else 0,
        "leads": [leads[d] for d in days],
        "bookings": [booked[d] for d in days] if p.can_bookings else None,
        "booking_value": [round(value[d], 2) for d in days] if p.can_revenue else None,
        "net_collected": [round(cash[d], 2) for d in days] if p.can_revenue else None,
    }


def _pipeline(db: Session, p: Params) -> list[dict]:
    rows = (db.query(PipelineStage.label, PipelineStage.category, PipelineStage.is_closed_won, PipelineStage.is_closed_lost,
                     PipelineStage.order, func.count(Inquiry.id))
            .join(Inquiry, Inquiry.stage_id == PipelineStage.id).filter(*_lead_conditions(p, p.start, p.end))
            .group_by(PipelineStage.id, PipelineStage.label, PipelineStage.category, PipelineStage.is_closed_won,
                      PipelineStage.is_closed_lost, PipelineStage.order).order_by(PipelineStage.order).all())
    return [{"stage": r[0], "category": r[1], "won": bool(r[2]), "lost": bool(r[3]), "count": r[5]} for r in rows]


# ── sources, Meta Ads, agents ────────────────────────────────────────────────────────────────────────────────

def _source_rows(db: Session, p: Params) -> list[dict]:
    leads = defaultdict(lambda: {"leads": 0, "bookings": 0, "value": 0.0, "label": "Other"})
    for source, n in db.query(Inquiry.source, func.count(Inquiry.id)).filter(*_lead_conditions(p, p.start, p.end)).group_by(Inquiry.source).all():
        key, label = dashboard_service._SOURCE_GROUPS.get(str(getattr(source, "value", source) or "other"), ("other", "Other"))
        leads[key]["leads"] += n
        leads[key]["label"] = label
    conds = _lead_conditions(p, p.start, p.end)
    if p.can_bookings:
        for source, n, v in (db.query(Inquiry.source, func.count(func.distinct(Stay.id)), func.coalesce(func.sum(Stay.total_amount), 0))
                             .join(Stay, Stay.inquiry_id == Inquiry.id)
                             .filter(*conds, Stay.tenant_id == p.tid, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)))
                             .group_by(Inquiry.source).all()):
            key, _ = dashboard_service._SOURCE_GROUPS.get(str(getattr(source, "value", source) or "other"), ("other", "Other"))
            leads[key]["bookings"] += n
            leads[key]["value"] += float(v or 0)
    return [{"key": k, "label": v["label"], "leads": v["leads"],
             "bookings": v["bookings"] if p.can_bookings else None, "booking_value": _money(p, v["value"]) if p.can_bookings else None}
            for k, v in sorted(leads.items(), key=lambda kv: -kv[1]["leads"])]


def _meta_ads(db: Session, p: Params) -> dict:
    """Meta Ads for the period: what Meta reports, and what HAIP can verify. Spend is Meta's own figure; leads and
    bookings count only when an ad referral was recorded against the conversation (LeadAttribution)."""
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
    bookings, value = 0, 0.0
    if inquiry_ids and p.can_bookings:
        bookings, value = db.query(func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0)).filter(
            Stay.tenant_id == p.tid, Stay.inquiry_id.in_(inquiry_ids), Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES))).one()
    chats = int(chats or 0)
    return {
        "configured": True, "last_synced_at": cfg.get("last_synced_at"), "last_error": cfg.get("last_error"),
        "spend": _money(p, float(spend or 0)),
        "reported_chats": chats,                                  # platform-reported
        "verified_conversations": len({a.conversation_id for a in atts}),   # HAIP-recorded referrals
        "verified_leads": len(inquiry_ids), "verified_bookings": int(bookings or 0) if p.can_bookings else None,
        "verified_booking_value": _money(p, float(value or 0)) if p.can_bookings else None,
        "cost_per_verified_lead": _money(p, float(spend) / len(inquiry_ids)) if inquiry_ids and spend else None,
        "return_on_spend": round(float(value or 0) / float(spend), 2) if p.can_revenue and p.can_bookings and spend else None,
        "not_traced": max(0, chats - len({a.conversation_id for a in atts})),
        "basis": "Spend and chats are Meta's figures. Leads and bookings count only chats where HAIP recorded the ad referral; "
                 "bookings are those linked to those leads (any time since).",
    }


def _agents(db: Session, p: Params) -> Optional[list[dict]]:
    if not (p.tenant_wide and p.scope_user_id is None):
        return None
    conds = _lead_conditions(p, p.start, p.end)
    rows = defaultdict(lambda: {"leads": 0, "bookings": 0, "value": 0.0})
    for uid, n in db.query(Inquiry.assigned_to, func.count(Inquiry.id)).filter(*conds).group_by(Inquiry.assigned_to).all():
        rows[uid]["leads"] += n
    if p.can_bookings:
        for uid, n, v in (db.query(Inquiry.assigned_to, func.count(func.distinct(Stay.id)), func.coalesce(func.sum(Stay.total_amount), 0))
                          .join(Stay, Stay.inquiry_id == Inquiry.id)
                          .filter(*conds, Stay.tenant_id == p.tid, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)))
                          .group_by(Inquiry.assigned_to).all()):
            rows[uid]["bookings"] += n
            rows[uid]["value"] += float(v or 0)
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == p.tid, User.id.in_([u for u in rows if u])).all()) if rows else {}
    out = [{"agent_id": uid, "name": names.get(uid) if uid else "Unassigned", "leads": v["leads"],
            "bookings": v["bookings"] if p.can_bookings else None,
            "booking_value": _money(p, v["value"]) if p.can_bookings else None}
           for uid, v in rows.items() if uid is None or uid in names]
    return sorted(out, key=lambda r: -r["leads"])[:10]


# ── attention and freshness ──────────────────────────────────────────────────────────────────────────────────

def _attention(q: dict, bookings: Optional[dict]) -> list[dict]:
    items = [
        ("unassigned", "Leads nobody owns", q["unassigned"], None, "/dashboard/my-day"),
        ("waiting_reply", "Guests waiting for a reply", q["waiting_reply"], q["waiting_oldest_at"], "/dashboard/my-day"),
        ("missed_calls", "Missed calls not called back", q["missed_not_called_back"], q["missed_oldest_at"], "/dashboard/calls"),
        ("followups", "Follow-ups overdue", q["followups_overdue"], q["followups_oldest_due"], "/dashboard/my-day"),
    ]
    if bookings and not bookings.get("restricted"):
        items += [("payment_overdue", "Bookings with an overdue payment", bookings["payment_overdue"], None, "/dashboard/bookings"),
                  ("needs_payment", "Upcoming bookings still owing money", bookings["needs_payment"], None, "/dashboard/bookings")]
    return [{"key": k, "label": label, "count": n, "oldest_at": oldest, "href": href} for k, label, n, oldest, href in items]


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
    cur, prev = _cohort(db, p, p.start, p.end), _cohort(db, p, p.prev_start, p.prev_end)
    queue = dashboard_service.needs_you_now(db, tenant, p.scope_user_id)     # the shared work queue, read once

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
        "leads": _leads_block(db, p, cur, prev, queue),
        "bookings": bookings,
        "revenue": revenue,
        "funnel": _funnel(cur, prev),
        "series": _series(db, p),
        "pipeline": _pipeline(db, p),
        "sources": _source_rows(db, p),
        "meta_ads": _meta_ads(db, p) if p.tenant_wide else None,
        "agents": _agents(db, p),
        "attention": _attention(queue, bookings),
        "stale_integrations": _integrations(db, p) if p.tenant_wide else [],
        "insights": dashboard_service.top_insights(db, p.tid) if p.tenant_wide else [],
    }
