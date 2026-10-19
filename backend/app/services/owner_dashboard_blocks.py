"""Owner dashboard (layout A, 19 Oct 2026): the numbers under the "Needs attention" cards. Composition only; every figure is a
shared definition from kpi_metrics / lead_metrics / impact_metrics / sales_performance_service (KPI_METRIC_CATALOGUE.md):

  kpis       New leads (leads.identified_new), Qualified leads (leads.qualified_dated: phone + check-in date), Bookings made
             (stays.booked), Booked value with its rental / add-ons split (stays.booked_value), Payment received
             (payments.collected). Each for the period, with the equal period before it; no change against an empty baseline.
  target     D-24: this IST month's booked value against the workspace monthly target, pace = days elapsed / days in month.
  travel     When leads want to travel, by check-in week: open leads with a phone and a check-in date (people), and booked stays.
  stages     The period's enquiries from leads (people with a phone; D-22) by pipeline stage, Lost by reason, unqualified apart.
  caravans   Per property this month: booked value (stays.booked_value), nights booked (stays.occupied_nights), % of the month.
  ai_calls   Quotes the AI sales agent is holding for approval, open lead-autopilot suggestions, calls in the period with missed /
             returned (calls.missed_returned).
  team       Per selling agent this month: target vs achieved booked value, calls, leads owned, median first reply.

Visibility: booking counts need bookings.read, money needs revenue.read; what the viewer may not read is ``None`` inside the block
or the whole block is ``{"restricted": true}``. Never 0.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.lead_autopilot import LeadAutopilotEvent
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.sales_action import SalesAction
from app.models.sales_target import SCOPE_TENANT
from app.services import impact_metrics, kpi_metrics, lead_metrics, targets_service
from app.services.business_overview_common import Params, _change, _linked_stay_ids, people_filters
from app.services.date_presets import ist_range_to_utc

TRAVEL_WEEKS = 5
TOP = 3


def _month(today: date) -> tuple[date, date, int]:
    first = today.replace(day=1)
    days = calendar.monthrange(first.year, first.month)[1]
    return first, first.replace(day=days), days


def _scoped(p: Params) -> list:
    scoped = _linked_stay_ids(p)
    return [Stay.id.in_(scoped)] if scoped is not None else []


def _money(p: Params, v: Optional[float]) -> Optional[float]:
    return round(float(v), 2) if p.can_revenue and v is not None else None


# ── KPI row ──────────────────────────────────────────────────────────────────────────────────────────────────

def kpis(db: Session, p: Params) -> dict:
    f = people_filters(p)
    new, new_prev = (lead_metrics.count_new_leads(db, p.tid, s, e, **f) for s, e in ((p.start, p.end), (p.prev_start, p.prev_end)))
    q, q_prev = (lead_metrics.count_qualified_dated(db, p.tid, s, e, **f) for s, e in ((p.start, p.end), (p.prev_start, p.prev_end)))
    out = {
        "new_leads": {"count": new, "previous": new_prev, "change": _change(new, new_prev),
                      "basis": "people whose phone number was captured in the period (leads.identified_new)"},
        "qualified": {"count": q, "previous": q_prev, "change": _change(q, q_prev), "rate_of_new": round(q / new * 100, 1) if new else None,
                      "basis": "of the new leads, those with a check-in date on a non-spam enquiry (leads.qualified_dated)"},
    }
    if not (p.can_bookings or p.can_revenue):
        return {**out, "bookings": {"restricted": True}, "booked_value": {"restricted": True}, "payment_received": {"restricted": True}}
    cur = kpi_metrics.booked_value(db, p.tid, p.start, p.end, property_id=p.property_id, extra_filters=_scoped(p))
    prev = kpi_metrics.booked_value(db, p.tid, p.prev_start, p.prev_end, property_id=p.property_id, extra_filters=_scoped(p))
    out["bookings"] = ({"count": cur["count"], "previous": prev["count"], "change": _change(cur["count"], prev["count"]),
                        "basis": "bookings made in the period, cancelled excluded (stays.booked)"}
                       if p.can_bookings else {"restricted": True})
    if not p.can_revenue:
        return {**out, "booked_value": {"restricted": True}, "payment_received": {"restricted": True}}
    scoped = _scoped(p)
    cash = kpi_metrics.payment_totals(db, p.tid, date.fromisoformat(p.d_from), date.fromisoformat(p.d_to),
                                      property_id=p.property_id, extra_filters=scoped)
    cash_prev = kpi_metrics.payment_totals(db, p.tid, date.fromisoformat(p.prev_from), date.fromisoformat(p.prev_to),
                                           property_id=p.property_id, extra_filters=scoped)
    out["booked_value"] = {"total": round(cur["total"], 2), "rental": round(cur["rental"], 2), "add_ons": round(cur["add_ons"], 2),
                           "previous": round(prev["total"], 2), "change": _change(cur["total"], prev["total"]),
                           "basis": "rental (stay charge) + add-ons of the bookings made in the period (stays.booked_value)"}
    out["payment_received"] = {"amount": round(cash["collected"], 2), "previous": round(cash_prev["collected"], 2),
                               "change": _change(cash["collected"], cash_prev["collected"]), "refunds": round(cash["refunded"], 2),
                               "basis": "payments with a payment date in the period; refunds shown apart (payments.collected)"}
    return out


# ── monthly target (D-24) ────────────────────────────────────────────────────────────────────────────────────

def target(db: Session, p: Params, today: date) -> dict:
    if not p.can_revenue:
        return {"restricted": True}
    first, last, days = _month(today)
    base = {"restricted": False, "month": first.isoformat(), "from": first.isoformat(), "to": last.isoformat(),
            "days_in_month": days, "days_elapsed": today.day, "days_left": days - today.day,
            "basis": "booked value (rental + add-ons) of bookings made this month, IST days (D-24)"}
    if not p.tenant_wide or p.channel or p.property_id or p.scope_user_id:
        return {**base, "available": False, "reason": "The target is for the whole workspace; clear the filters to compare."}
    start, end, _, _ = ist_range_to_utc(first.isoformat(), last.isoformat())
    bv = kpi_metrics.booked_value(db, p.tid, start, end)
    cash = kpi_metrics.payment_totals(db, p.tid, first, today)
    row = targets_service.get_target(db, p.tid, SCOPE_TENANT, None, first)
    pace = today.day / days
    booked = {"total": round(bv["total"], 2), "rental": round(bv["rental"], 2), "add_ons": round(bv["add_ons"], 2), "count": bv["count"]}
    out = {**base, "booked": booked, "payment_received": round(cash["collected"], 2), "pace_pct": round(pace * 100, 1)}
    if row is None or not float(row.target_amount or 0):
        return {**out, "available": False, "reason": "No target is set for this month.", "href": "/dashboard/targets"}
    goal = float(row.target_amount)
    expected = goal * pace
    return {**out, "available": True, "target": round(goal, 2), "achieved_pct": round(bv["total"] / goal * 100, 1),
            "expected_by_today": round(expected, 2), "ahead_by": round(bv["total"] - expected, 2),
            "to_go": round(max(0.0, goal - bv["total"]), 2), "href": "/dashboard/targets"}


# ── when leads want to travel ────────────────────────────────────────────────────────────────────────────────

def _week_index(d: date, monday: date) -> int:
    return min(TRAVEL_WEEKS, (d - monday).days // 7)


def travel(db: Session, p: Params, today: date) -> dict:
    from app.services import work_queue_service as wq
    monday = today - timedelta(days=today.weekday())
    weeks = [{"start": (monday + timedelta(days=7 * i)).isoformat(), "active": 0, "booked": 0 if p.can_bookings else None}
             for i in range(TRAVEL_WEEKS)] + [{"start": None, "active": 0, "booked": 0 if p.can_bookings else None}]
    done = set(wq._done_stage_ids(db, p.tid))
    rows = (db.query(Inquiry.guest_id, Inquiry.check_in, Inquiry.stage_id, Inquiry.stage)
            .join(Guest, Guest.id == Inquiry.guest_id)
            .filter(Inquiry.tenant_id == p.tid, Inquiry.qualification_status != kpi_metrics.UNQUALIFIED,
                    Inquiry.check_in.isnot(None), Inquiry.check_in >= monday.isoformat(),
                    Guest.lead_identified_at.isnot(None), *lead_metrics.people(p.tid, **people_filters(p))).all())
    earliest: dict[str, date] = {}
    for guest_id, check_in, stage_id, stage in rows:
        if (stage_id and stage_id in done) or stage in (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED):
            continue
        try:
            d = date.fromisoformat(str(check_in)[:10])
        except ValueError:
            continue
        if d >= monday and (guest_id not in earliest or d < earliest[guest_id]):
            earliest[guest_id] = d
    for d in earliest.values():
        weeks[_week_index(d, monday)]["active"] += 1
    if p.can_bookings:
        q = db.query(Stay.check_in).filter(Stay.tenant_id == p.tid, Stay.status.in_(("confirmed", "checked_in")),
                                           Stay.check_in >= monday, *_scoped(p))
        if p.property_id:
            q = q.filter(Stay.property_id == p.property_id)
        for (ci,) in q.all():
            weeks[_week_index(ci, monday)]["booked"] += 1
    return {"weeks": weeks, "booked_restricted": not p.can_bookings,
            "active_basis": "open leads with a phone number and a check-in date, each person once (their earliest upcoming date)",
            "booked_basis": "confirmed bookings by check-in week"}


# ── leads by stage ───────────────────────────────────────────────────────────────────────────────────────────

def stages(db: Session, p: Params) -> dict:
    conds = [Inquiry.tenant_id == p.tid, Inquiry.created_at >= kpi_metrics.as_datetime(p.start),
             Inquiry.created_at <= kpi_metrics.as_datetime(p.end), Guest.lead_identified_at.isnot(None),
             *lead_metrics.people(p.tid, channel=p.channel)]
    if p.scope_user_id:
        conds.append(Inquiry.assigned_to == p.scope_user_id)
    if p.property_id:
        conds.append(Inquiry.property_id == p.property_id)
    base = db.query(Inquiry.stage_id, Inquiry.lost_reason, Inquiry.qualification_status).join(Guest, Guest.id == Inquiry.guest_id).filter(*conds)
    by_stage: dict = defaultdict(int)
    lost_by: dict = defaultdict(int)
    unqualified = 0
    catalogue = db.query(PipelineStage).filter(PipelineStage.tenant_id == p.tid).order_by(PipelineStage.order).all()
    lost_ids = {s.id for s in catalogue if s.is_closed_lost}
    for stage_id, lost_reason, qualification in base.all():
        if qualification == kpi_metrics.UNQUALIFIED:
            unqualified += 1
            continue
        by_stage[stage_id] += 1
        if stage_id in lost_ids:
            key = getattr(lost_reason, "value", lost_reason)
            lost_by[key] += 1
    rows = [{"key": s.key, "label": s.label, "category": s.category, "won": bool(s.is_closed_won), "lost": bool(s.is_closed_lost),
             "count": by_stage.get(s.id, 0)} for s in catalogue]
    if by_stage.get(None):
        rows.append({"key": "no_stage", "label": "No stage", "category": None, "won": False, "lost": False, "count": by_stage[None]})
    lost = [{"reason": k or "not_recorded", "label": impact_metrics.LOST_REASON_LABELS.get(k, str(k).replace("_", " ").title()), "count": n}
            for k, n in sorted(lost_by.items(), key=lambda kv: -kv[1])]
    return {"stages": rows, "lost_by_reason": lost, "unqualified": unqualified,
            "basis": "enquiries created in the period by people with a phone number, by the stage they are in now; "
                     "a DM that never shared a number is not counted. Unqualified (spam) is counted apart."}


# ── caravans / properties this month ─────────────────────────────────────────────────────────────────────────

def caravans(db: Session, p: Params, today: date) -> dict:
    if not p.can_bookings:
        return {"restricted": True}
    first, last, days = _month(today)
    start, end, _, _ = ist_range_to_utc(first.isoformat(), last.isoformat())
    value: dict = defaultdict(float)
    for r in kpi_metrics.booked_value_rows(db, p.tid, start, end, property_id=p.property_id, extra_filters=_scoped(p)):
        value[r["property_id"]] += r["rental"] + r["add_ons"]
    q = db.query(Property).filter(Property.tenant_id == p.tid, Property.is_active.isnot(False))
    if p.property_id:
        q = q.filter(Property.id == p.property_id)
    items = []
    for prop in sorted(q.all(), key=lambda x: (x.name or "").lower()):
        nights = kpi_metrics.occupied_nights(db, p.tid, first, last + timedelta(days=1), property_ids=[prop.id])
        placeholder = (prop.name or "").strip().lower() == "unassigned"
        if placeholder and not nights and not value.get(prop.id):
            continue
        items.append({"property_id": prop.id, "name": prop.name, "booked_value": _money(p, value.get(prop.id, 0.0)),
                      "nights": nights, "occupancy_pct": round(nights / days * 100) if days else None})
    return {"restricted": False, "month": first.isoformat(), "days_in_month": days, "items": items,
            "basis": "booked value = bookings made this month (rental + add-ons); nights = nights stayed this month, any booking date"}


# ── AI and calls ─────────────────────────────────────────────────────────────────────────────────────────────

def _guest_names(db: Session, tid: str, inquiry_ids: set) -> dict:
    if not inquiry_ids:
        return {}
    return {iid: name for iid, name in db.query(Inquiry.id, Guest.name).join(Guest, Guest.id == Inquiry.guest_id)
            .filter(Inquiry.tenant_id == tid, Inquiry.id.in_(list(inquiry_ids))).all()}


def ai_calls(db: Session, p: Params) -> Optional[dict]:
    if not p.tenant_wide:
        return None
    pending = (db.query(SalesAction).filter(SalesAction.tenant_id == p.tid, SalesAction.status == "pending")
               .order_by(SalesAction.created_at.desc()))
    n_pending = pending.count()
    top_actions = pending.limit(TOP).all()
    suggested = (db.query(LeadAutopilotEvent, PipelineStage.label).join(PipelineStage, PipelineStage.id == LeadAutopilotEvent.to_stage_id)
                 .filter(LeadAutopilotEvent.tenant_id == p.tid, LeadAutopilotEvent.status == "suggested")
                 .order_by(LeadAutopilotEvent.created_at.desc()).limit(200).all())
    names = _guest_names(db, p.tid, {a.inquiry_id for a in top_actions} | {e.inquiry_id for e, _ in suggested[:TOP]})
    by_target: dict = defaultdict(int)
    for _, label in suggested:
        by_target[label] += 1
    calls_q = db.query(func.count(Call.id)).filter(Call.tenant_id == p.tid, Call.is_sample.is_(False),
                                                    Call.created_at >= kpi_metrics.as_datetime(p.start),
                                                    Call.created_at <= kpi_metrics.as_datetime(p.end))
    missed = impact_metrics.missed_calls(db, p.tid, p.start, p.end)
    return {
        "sales_actions": {"count": n_pending, "href": "/dashboard/inbox",
                          "items": [{"name": names.get(a.inquiry_id) or "Lead", "package": (a.summary or {}).get("package"),
                                     "href": f"/dashboard/leads/{a.inquiry_id}"} for a in top_actions]},
        "autopilot": {"count": len(suggested), "href": "/dashboard/settings/lead-autopilot",
                      "by_stage": [{"label": k, "count": v} for k, v in sorted(by_target.items(), key=lambda kv: -kv[1])],
                      "items": [{"name": names.get(e.inquiry_id) or "Lead", "to": label, "reason": e.reason,
                                 "href": f"/dashboard/leads/{e.inquiry_id}"} for e, label in suggested[:TOP]]},
        "calls": {"total": int(calls_q.scalar() or 0), "missed": missed["missed"], "returned": missed["returned"],
                  "not_returned": missed["missed"] - missed["returned"], "href": "/dashboard/calls"},
    }


# ── team this month ──────────────────────────────────────────────────────────────────────────────────────────

def team(db: Session, p: Params, today: date) -> Optional[dict]:
    if not (p.tenant_wide and p.scope_user_id is None):
        return None
    from app.services import sales_performance_service
    first, last, _ = _month(today)
    start, end, _, _ = ist_range_to_utc(first.isoformat(), today.isoformat())
    perf = sales_performance_service.agent_performance(db, p.tid, first)
    calls = dict(db.query(Call.agent_id, func.count(Call.id)).filter(
        Call.tenant_id == p.tid, Call.agent_id.isnot(None), Call.is_sample.is_(False),
        Call.created_at >= kpi_metrics.as_datetime(start), Call.created_at <= kpi_metrics.as_datetime(end)).group_by(Call.agent_id).all())
    owned = lead_metrics.by_owner(db, p.tid, start, end, with_bookings=False)
    replies: dict = defaultdict(list)
    for t in impact_metrics.guest_turns(db, p.tid, start, end)["turns"]:
        if t["reply_seconds"] is not None and t["responder"] != "ai" and t.get("sender_id"):
            replies[t["sender_id"]].append(t["reply_seconds"])
    rows = []
    for a in perf["agents"]:
        rows.append({"agent_id": a["agent_id"], "name": a["name"],
                     "target": _money(p, a["target"]) if a["target"] else None,
                     "achieved": _money(p, a["revenue"]),
                     "achieved_pct": round(a["achieved_pct"], 1) if p.can_revenue and a["achieved_pct"] is not None else None,
                     "calls": int(calls.get(a["agent_id"], 0)), "leads_owned": owned.get(a["agent_id"], {}).get("leads", 0),
                     "median_first_reply_seconds": impact_metrics.percentile(replies.get(a["agent_id"], []), 0.5)})
    return {"month": first.isoformat(), "from": first.isoformat(), "to": today.isoformat(), "rows": rows,
            "unattributed": _money(p, perf["unattributed"]),
            "basis": "this month: booked value credited through the booking's enquiry owner (Targets page rule, D-24), calls the person "
                     "handled, new leads they own, median time to their first reply to a guest turn"}
