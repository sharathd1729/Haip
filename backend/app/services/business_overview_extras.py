"""More blocks of the Business Overview, kept apart from business_overview_service.py so each file stays readable:
lead extras (lost, expected check-in), booking breakdowns, the day / week / month trend, Meta Ads detail with campaigns,
the agent table and the high-intent-at-risk list.

Same rules as the service: compose existing definitions, return ``None`` (never 0) for what the viewer may not see,
credit a booking to a source or an agent only through its lead link, and read the IST day.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad_metrics import AdMetric
from app.models.call import Call
from app.models.conversation import Message, MessageDirection
from app.models.inquiry import Inquiry
from app.models.lead_attribution import LeadAttribution
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.user import User
from app.services import dashboard_service, kpi_metrics
from app.services.agent_analytics_service import get_agent_scorecard_rows
from app.services.business_overview_common import (
    Params, _ist_day, _lead_conditions, _linked_stay_ids, _money, _stay_conditions,
)
from app.services.date_presets import ist_range_to_utc

LIVE_STATUSES = ("confirmed", "checked_in")
TREND_BUCKETS = 12          # weeks or months shown by the week / month trend


# ── leads ────────────────────────────────────────────────────────────────────────────────────────────────────

def leads_extras(db: Session, p: Params) -> dict:
    conds = _lead_conditions(p, p.start, p.end)
    lost = (db.query(func.count(Inquiry.id)).join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
            .filter(*conds, PipelineStage.is_closed_lost.is_(True)).scalar() or 0)
    months: dict[str, int] = defaultdict(int)
    unknown = 0
    for (check_in,) in db.query(Inquiry.check_in).filter(*conds).all():
        key = (check_in or "")[:7]
        if len(key) == 7 and key[4] == "-" and key[:4].isdigit() and key[5:].isdigit():
            months[key] += 1
        else:
            unknown += 1
    return {"lost": lost,
            "by_expected_check_in": [{"month": m, "count": n} for m, n in sorted(months.items())[:8]],
            "expected_check_in_unknown": unknown}


# ── bookings ─────────────────────────────────────────────────────────────────────────────────────────────────

def bookings_extras(db: Session, p: Params, today: date) -> dict:
    out_q = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == p.tid, Stay.status.in_(LIVE_STATUSES),
        Stay.check_out >= today, Stay.check_out <= today + timedelta(days=6))
    if p.property_id:
        out_q = out_q.filter(Stay.property_id == p.property_id)
    scoped = _linked_stay_ids(p)
    if scoped is not None:
        out_q = out_q.filter(Stay.id.in_(scoped))

    conds = _stay_conditions(p, p.start, p.end)
    by_property = [
        {"property_id": pid, "name": name, "bookings": int(n), "value": _money(p, float(v or 0))}
        for pid, name, n, v in (db.query(Stay.property_id, Property.name, func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0))
                                .join(Property, Property.id == Stay.property_id).filter(*conds)
                                .group_by(Stay.property_id, Property.name).order_by(func.count(Stay.id).desc()).limit(8).all())
    ]
    # A booking with no recorded channel is a direct one (how HAIP's own booking forms record it); fold both together.
    channels: dict[str, list] = {}
    for ch, n, v in (db.query(Stay.channel_source, func.count(Stay.id), func.coalesce(func.sum(Stay.total_amount), 0))
                     .filter(*conds).group_by(Stay.channel_source).all()):
        slot = channels.setdefault(ch or "direct", [0, 0.0])
        slot[0] += int(n)
        slot[1] += float(v or 0)
    by_channel = [{"channel": ch, "bookings": n, "value": _money(p, v)}
                  for ch, (n, v) in sorted(channels.items(), key=lambda kv: -kv[1][0])[:8]]
    return {"upcoming_checkouts": int(out_q.scalar() or 0), "by_property": by_property, "by_channel": by_channel}


# ── trend: day, week or month ────────────────────────────────────────────────────────────────────────────────

def _bucket(d: date, granularity: str) -> date:
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    return d


def _buckets(p: Params) -> list[date]:
    d_from, d_to = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    if p.trend == "day":
        return dashboard_service._day_list(d_from, d_to)
    last = _bucket(d_to, p.trend)
    out = [last]
    for _ in range(TREND_BUCKETS - 1):
        prev = out[0] - timedelta(days=1)
        out.insert(0, _bucket(prev, p.trend))
    return out


def _bucket_end(start: date, granularity: str) -> date:
    if granularity == "day":
        return start
    if granularity == "week":
        return start + timedelta(days=6)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def trend_series(db: Session, p: Params) -> dict:
    g = p.trend
    keys = _buckets(p)
    d_from, d_to = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    start, end = dashboard_service._utc_bounds([keys[0], d_to])
    leads, booked, value, cash = defaultdict(int), defaultdict(int), defaultdict(float), defaultdict(float)
    for (created,) in db.query(Inquiry.created_at).filter(*_lead_conditions(p, start, end)).all():
        leads[_bucket(_ist_day(created), g)] += 1
    if p.can_bookings:
        for created, amount in db.query(Stay.created_at, Stay.total_amount).filter(*_stay_conditions(p, start, end)).all():
            k = _bucket(_ist_day(created), g)
            booked[k] += 1
            value[k] += float(amount or 0)
    if p.can_revenue:
        q = (db.query(StayPayment.paid_on, StayPayment.kind, StayPayment.amount).join(Stay, Stay.id == StayPayment.stay_id)
             .filter(StayPayment.tenant_id == p.tid, StayPayment.paid_on >= keys[0], StayPayment.paid_on <= d_to))
        if p.property_id:
            q = q.filter(Stay.property_id == p.property_id)
        scoped = _linked_stay_ids(p)
        if scoped is not None:
            q = q.filter(Stay.id.in_(scoped))
        for paid_on, kind, amount in q.all():
            cash[_bucket(paid_on, g)] += float(amount) * (-1 if kind == "refund" else 1)
    first_in_period = next((i for i, k in enumerate(keys) if _bucket_end(k, g) >= d_from), 0)
    return {
        "granularity": g,
        "days": [k.isoformat() for k in keys],
        "period_start_index": first_in_period,
        "leads": [leads[k] for k in keys],
        "bookings": [booked[k] for k in keys] if p.can_bookings else None,
        "booking_value": [round(value[k], 2) for k in keys] if p.can_revenue else None,
        "net_collected": [round(cash[k], 2) for k in keys] if p.can_revenue else None,
    }


# ── Meta Ads detail ──────────────────────────────────────────────────────────────────────────────────────────

def meta_detail(db: Session, p: Params) -> dict:
    """Delivery numbers Meta reports (impressions, clicks, CTR, CPC, CPM) and the top campaigns, with the leads HAIP
    verified for each. Spend-based figures follow the same visibility rule as spend."""
    f, t = date.fromisoformat(p.d_from), date.fromisoformat(p.d_to)
    rows = (db.query(AdMetric.campaign_id, AdMetric.campaign_name, func.sum(AdMetric.spend), func.sum(AdMetric.impressions),
                     func.sum(AdMetric.clicks), func.sum(AdMetric.conversations_started))
            .filter(AdMetric.tenant_id == p.tid, AdMetric.date >= f, AdMetric.date <= t)
            .group_by(AdMetric.campaign_id, AdMetric.campaign_name).all())
    spend = sum(float(r[2] or 0) for r in rows)
    impressions = sum(int(r[3] or 0) for r in rows)
    clicks = sum(int(r[4] or 0) for r in rows)

    ad_campaign = dict(db.query(AdMetric.ad_id, AdMetric.campaign_id).filter(AdMetric.tenant_id == p.tid).distinct().all())
    start_dt, end_dt = ist_range_to_utc(p.d_from, p.d_to)[2:]
    verified: dict[str, set] = defaultdict(set)
    for a in db.query(LeadAttribution).filter(LeadAttribution.tenant_id == p.tid, LeadAttribution.created_at >= start_dt,
                                              LeadAttribution.created_at <= end_dt).all():
        cid = a.campaign_id or ad_campaign.get(a.ad_id or "", "")
        verified[cid].add(a.conversation_id)
    campaigns = [
        {"campaign_id": cid, "name": name or "Campaign", "spend": _money(p, float(s or 0)), "impressions": int(i or 0),
         "clicks": int(c or 0), "reported_chats": int(chats or 0), "verified_conversations": len(verified.get(cid, ()))}
        for cid, name, s, i, c, chats in sorted(rows, key=lambda r: -float(r[2] or 0))[:5]
    ]
    return {
        "impressions": impressions, "clicks": clicks,
        "ctr": round(clicks / impressions * 100, 2) if impressions else None,
        "cpc": _money(p, spend / clicks) if clicks else None,
        "cpm": _money(p, spend / impressions * 1000) if impressions else None,
        "campaigns": campaigns,
    }


# ── agents ───────────────────────────────────────────────────────────────────────────────────────────────────

def agent_table(db: Session, p: Params) -> Optional[list[dict]]:
    """One row per agent for the owner view: what they were given, what they did, and what became of it."""
    if not (p.tenant_wide and p.scope_user_id is None):
        return None
    conds = _lead_conditions(p, p.start, p.end)
    rows = defaultdict(lambda: {"leads": 0, "valid": 0, "invalid": 0, "bookings": 0, "value": 0.0})
    for uid, cat, n in (db.query(Inquiry.assigned_to, PipelineStage.category, func.count(Inquiry.id))
                        .outerjoin(PipelineStage, PipelineStage.id == Inquiry.stage_id).filter(*conds)
                        .group_by(Inquiry.assigned_to, PipelineStage.category).all()):
        rows[uid]["leads"] += n
        if cat in ("valid", "invalid"):
            rows[uid][cat] += n
    if p.can_bookings:
        for uid, n, v in (db.query(Inquiry.assigned_to, func.count(func.distinct(Stay.id)), func.coalesce(func.sum(Stay.total_amount), 0))
                          .join(Stay, Stay.inquiry_id == Inquiry.id)
                          .filter(*conds, Stay.tenant_id == p.tid, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)))
                          .group_by(Inquiry.assigned_to).all()):
            rows[uid]["bookings"] += n
            rows[uid]["value"] += float(v or 0)

    start_dt, end_dt = ist_range_to_utc(p.d_from, p.d_to)[2:]
    messages = dict(db.query(Message.sender_id, func.count(Message.id)).filter(
        Message.tenant_id == p.tid, Message.direction == MessageDirection.OUTBOUND, Message.sender_id.isnot(None),
        Message.is_internal.is_(False), Message.is_ai_generated.isnot(True),
        Message.created_at >= start_dt, Message.created_at <= end_dt).group_by(Message.sender_id).all())
    scores = dict(db.query(Call.agent_id, func.avg(Call.ai_score)).filter(
        Call.tenant_id == p.tid, Call.agent_id.isnot(None), Call.ai_score.isnot(None),
        Call.created_at >= start_dt, Call.created_at <= end_dt).group_by(Call.agent_id).all())
    card = {r["agent_id"]: r for r in get_agent_scorecard_rows(db, p.tid, p.d_from, p.d_to)}
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == p.tid).all())

    out = []
    for uid in set(rows) | {u for u, r in card.items() if r["calls_answered"] or r["calls_missed"] or r["followups_total"]} | set(messages):
        if uid is not None and uid not in names:
            continue
        r, c = rows[uid], card.get(uid, {})
        responded = (c.get("response_count") or 0) > 0
        out.append({
            "agent_id": uid, "name": names.get(uid) if uid else "Unassigned",
            "leads": r["leads"], "valid": r["valid"], "invalid": r["invalid"],
            "bookings": r["bookings"] if p.can_bookings else None,
            "booking_value": _money(p, r["value"]) if p.can_bookings else None,
            "calls_answered": c.get("calls_answered", 0), "calls_missed": c.get("calls_missed", 0),
            "callbacks_waiting": max(0, c.get("calls_missed", 0) - c.get("calls_missed_recovered", 0)),
            "avg_response_seconds": round(c["avg_response_seconds"]) if responded else None,
            "messages_sent": int(messages.get(uid, 0)),
            "followups_total": c.get("followups_total", 0), "followups_completed": c.get("followups_completed", 0),
            "followups_overdue": c.get("followups_overdue", 0),
            "ai_drafts_approved": c.get("ai_drafts_approved", 0), "ai_drafts_total": c.get("ai_drafts_total", 0),
            "avg_call_score": round(float(scores[uid]), 1) if uid in scores else None,
        })
    return sorted(out, key=lambda a: (-a["leads"], a["name"] or ""))[:12]


# ── high-intent leads at risk ────────────────────────────────────────────────────────────────────────────────

def high_intent_at_risk(db: Session, p: Params, queue: dict) -> dict:
    """Open leads the AI read as positive ("hot", the lead-quality label already used on Leads activity) that nobody
    owns, that are waiting for a reply, or whose follow-up is overdue. Built from the shared work queue; no new rule."""
    reasons: dict[str, tuple[str, str, str]] = {}
    labels = {"unassigned": "nobody owns it", "reply": "waiting for a reply", "followup": "follow-up overdue"}
    for item in queue.get("items", []):
        iid = item.get("inquiry_id")
        if iid and item["kind"] in labels and iid not in reasons:
            reasons[iid] = (item.get("title") or "Lead", labels[item["kind"]], item.get("href") or f"/dashboard/leads/{iid}")
    if not reasons:
        return {"count": 0, "items": []}
    hot = [iid for iid, analysis in db.query(Inquiry.id, Inquiry.ai_analysis).filter(
        Inquiry.tenant_id == p.tid, Inquiry.id.in_(list(reasons))).all()
        if isinstance(analysis, dict) and analysis.get("sentiment") == "positive"]
    items = [{"inquiry_id": i, "name": reasons[i][0], "reason": reasons[i][1], "href": reasons[i][2]} for i in hot]
    return {"count": len(items), "items": items[:5]}
