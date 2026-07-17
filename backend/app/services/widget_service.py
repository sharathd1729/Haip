"""
Widget service — computes and caches adaptive dashboard widget snapshots.

Every public function in this module reads from existing analytics helpers.
No new raw SQL queries; no LLM calls inline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Literal, Optional
import structlog

from sqlalchemy.orm import Session
from sqlalchemy import func, false as sa_false

from app.models.tenant import Tenant
from app.models.call import Call
from app.models.inquiry import Inquiry, InquiryStage
from app.models.conversation import Message, MessageDirection
from app.models.property import Stay, Property
from app.models.integration import Integration
from app.models.dashboard_widget import DashboardWidget
from app.api.v1.endpoints.analytics import (
    _calls_week_series, _p95_seconds, _revenue_at_risk, _delta, _date_range,
)

log = structlog.get_logger()

WidgetState = Literal["unavailable", "early_signal", "full_insight"]

# ─── Registry ─────────────────────────────────────────────────────────────────

@dataclass
class WidgetDef:
    key: str
    title: str
    description: str
    category: str          # calls | messaging | revenue | guests
    required_modules: list[str]   # subset of: ivr, whatsapp, instagram, bookings, properties
    min_rows: int          # minimum data rows to move out of early_signal
    refresh_hours: int


WIDGET_REGISTRY: dict[str, WidgetDef] = {d.key: d for d in [
    WidgetDef("call_volume",        "Call Volume",          "Daily call count + QA trend",          "calls",     ["ivr"],                        5,  4),
    WidgetDef("sentiment",          "Call Sentiment",       "AI-scored call sentiment breakdown",   "calls",     ["ivr"],                        5,  4),
    WidgetDef("missed_revenue",     "Missed Revenue",       "Lost-inquiry revenue at risk",         "calls",     ["ivr"],                        3,  6),
    WidgetDef("objections",         "Top Objections",       "Recurring guest objection patterns",   "calls",     ["ivr"],                        5,  6),
    WidgetDef("intent_mix",         "Intent Mix",           "What guests are asking about",         "calls",     ["ivr"],                        10, 6),
    WidgetDef("response_time",      "Response Time",        "p95 first-reply latency",              "messaging", [],                             5,  4),
    WidgetDef("agent_leaderboard",  "Agent Leaderboard",    "Concierge QA score ranking",           "calls",     ["ivr"],                        5,  4),
    WidgetDef("inquiry_funnel",     "Inquiry Funnel",       "Stage-by-stage conversion",            "revenue",   [],                             10, 6),
    WidgetDef("channel_mix",        "Channel Mix",          "Inbound volume by channel",            "messaging", ["whatsapp"],                   10, 4),
    WidgetDef("attribution",        "Lead Attribution",     "Which sources drive bookings",         "revenue",   [],                             10, 24),
    WidgetDef("campaign_performance","Campaign Performance","WhatsApp blast outcomes",              "messaging", ["whatsapp"],                   5,  6),
    WidgetDef("guest_ltv",          "Guest LTV",            "Lifetime revenue per guest",           "guests",    [],                             20, 24),
    WidgetDef("occupancy_forecast", "Occupancy Forecast",   "30-day forward occupancy",             "revenue",   ["properties", "bookings"],     10, 24),
    WidgetDef("revenue_forecast",   "Revenue Forecast",     "30-day projected revenue",             "revenue",   ["properties", "bookings"],     10, 24),
    WidgetDef("pricing",            "Pricing Signals",      "Rate vs. occupancy optimisation",      "revenue",   ["properties", "bookings"],     10, 24),
    WidgetDef("churn_risk",         "Churn Risk",           "Guests likely not to return",          "guests",    ["bookings"],                   10, 24),
    WidgetDef("cohorts",            "Guest Cohorts",        "Repeat vs. new guest trends",          "guests",    ["bookings"],                   20, 24),
    WidgetDef("ai_recommendations", "AI Recommendations",   "Prioritised action suggestions",       "calls",     [],                             0,  6),
]}

# ─── Default sets ─────────────────────────────────────────────────────────────

_DEFAULTS: dict[str, list[str]] = {
    "ivr_only":    ["call_volume", "objections", "missed_revenue", "sentiment", "agent_leaderboard"],
    # intent_mix requires the "ivr" module (calls-only) -- a chat-only
    # tenant was previously defaulted into an always-"unavailable" tile.
    # inquiry_funnel needs no module and now reflects the tenant's real
    # Leads360 taxonomy (pipeline_stages), directly showing off pipeline
    # health for a WhatsApp/Instagram-only tenant.
    "wa_only":     ["channel_mix", "response_time", "inquiry_funnel", "ai_recommendations", "attribution"],
    "full_stack":  ["call_volume", "objections", "intent_mix", "occupancy_forecast", "ai_recommendations", "inquiry_funnel"],
    "fresh":       ["ai_recommendations", "inquiry_funnel", "response_time", "guest_ltv"],
}


# ─── Module detection ─────────────────────────────────────────────────────────

def detect_modules(db: Session, tenant: Tenant) -> set[str]:
    modules: set[str] = set()
    if tenant.voice_platform:
        modules.add("ivr")
    if tenant.whatsapp_phone_number_id:
        modules.add("whatsapp")
    ig = db.query(Integration).filter(
        Integration.tenant_id == tenant.id,
        Integration.kind == "instagram",
        Integration.status == "active",
    ).first()
    if ig:
        modules.add("instagram")
    if db.query(Stay.id).filter(Stay.tenant_id == tenant.id).first():
        modules.add("bookings")
    if db.query(Property.id).filter(Property.tenant_id == tenant.id).first():
        modules.add("properties")
    return modules


def get_default_widgets(modules: set[str]) -> list[str]:
    has_ivr = "ivr" in modules
    has_wa  = "whatsapp" in modules or "instagram" in modules
    if has_ivr and has_wa:
        return _DEFAULTS["full_stack"]
    if has_ivr:
        return _DEFAULTS["ivr_only"]
    if has_wa:
        return _DEFAULTS["wa_only"]
    return _DEFAULTS["fresh"]


# ─── State computation ────────────────────────────────────────────────────────

def compute_widget_state(
    db: Session,
    tenant: Tenant,
    widget_key: str,
    modules: set[str],
) -> WidgetState:
    defn = WIDGET_REGISTRY.get(widget_key)
    if not defn:
        return "unavailable"
    # check required modules
    for m in defn.required_modules:
        if m not in modules:
            return "unavailable"
    if defn.min_rows == 0:
        return "full_insight"
    # count relevant rows
    row_count = _count_rows(db, tenant.id, widget_key)
    if row_count < defn.min_rows:
        return "early_signal"
    return "full_insight"


def _count_rows(db: Session, tid: str, widget_key: str) -> int:
    now = datetime.now(timezone.utc)
    start_30d = now - timedelta(days=30)
    if widget_key in ("call_volume", "sentiment", "missed_revenue", "objections",
                       "intent_mix", "agent_leaderboard"):
        return db.query(func.count(Call.id)).filter(
            Call.tenant_id == tid,
            Call.started_at >= start_30d,
        ).scalar() or 0
    if widget_key in ("response_time", "channel_mix", "campaign_performance"):
        return db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.created_at >= start_30d,
        ).scalar() or 0
    if widget_key in ("inquiry_funnel", "attribution"):
        return db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tid,
        ).scalar() or 0
    if widget_key in ("occupancy_forecast", "revenue_forecast", "pricing",
                       "churn_risk", "cohorts", "guest_ltv"):
        return db.query(func.count(Stay.id)).filter(
            Stay.tenant_id == tid,
        ).scalar() or 0
    return 0


# ─── Widget data builders ─────────────────────────────────────────────────────

def build_widget_data(
    db: Session,
    tenant: Tenant,
    widget_key: str,
    range_days: int = 30,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (data_dict, summary_text). Raises ValueError for unknown key."""
    tid = tenant.id
    now = datetime.now(timezone.utc)
    start, end = _date_range(range_days, now)
    fn = _BUILDERS.get(widget_key)
    if fn is None:
        raise ValueError(f"Unknown widget key: {widget_key}")
    try:
        return fn(db, tid, start, end, now)
    except Exception as exc:  # noqa: BLE001
        log.warning("widget_build_failed", widget=widget_key, tenant=tid, error=str(exc))
        return None, None


# ─── Individual builders ──────────────────────────────────────────────────────

def _call_volume(db, tid, start, end, now):
    series = _calls_week_series(db, tid, start, end)
    total = sum(p.count for p in series)
    latest_score = series[-1].avg_score if series else 0.0
    data = {
        "series": [{"date": p.date, "count": p.count, "avg_score": p.avg_score} for p in series],
        "total_calls": total,
        "avg_qa_score": latest_score,
    }
    summary = f"{total} calls over last {len(series)} days, avg QA {latest_score:.0f}/10."
    return data, summary


def _sentiment(db, tid, start, end, now):
    from sqlalchemy import case
    rows = db.query(
        func.count(Call.id).label("total"),
        func.sum(case((Call.sentiment == "positive", 1), else_=0)).label("pos"),
        func.sum(case((Call.sentiment == "negative", 1), else_=0)).label("neg"),
        func.sum(case((Call.sentiment == "neutral",  1), else_=0)).label("neu"),
    ).filter(Call.tenant_id == tid, Call.started_at >= start, Call.sentiment.isnot(None)).first()
    if not rows or not rows.total:
        return {"positive": 0, "negative": 0, "neutral": 0, "total": 0}, "No sentiment data yet."
    total = rows.total
    data = {
        "positive": int(rows.pos or 0),
        "negative": int(rows.neg or 0),
        "neutral":  int(rows.neu or 0),
        "total":    total,
    }
    pct_pos = round(data["positive"] / total * 100)
    summary = f"{pct_pos}% positive sentiment across {total} analyzed calls."
    return data, summary


def _missed_revenue(db, tid, start, end, now):
    from app.services.pipeline_stage_service import get_stage_ids_by_flag
    at_risk = _revenue_at_risk(db, tid)
    lost_ids = get_stage_ids_by_flag(db, tid, is_closed_lost=True)
    lost_count = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage_id.in_(lost_ids) if lost_ids else sa_false(),
        Inquiry.updated_at >= start,
    ).scalar() or 0
    data = {"revenue_at_risk": at_risk or 0, "lost_inquiries": lost_count}
    if at_risk:
        summary = f"₹{at_risk:,.0f} revenue at risk from {lost_count} lost inquiries."
    else:
        summary = f"{lost_count} inquiries closed lost this period."
    return data, summary


def _objections(db, tid, start, end, now):
    from app.models.call import Call
    rows = db.query(Call.objections).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
        Call.objections.isnot(None),
    ).all()
    counts: dict[str, int] = {}
    for (obj_list,) in rows:
        if isinstance(obj_list, list):
            for o in obj_list:
                counts[o] = counts.get(o, 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    data = {"objections": [{"label": k, "count": v} for k, v in top]}
    summary = f"Top objection: '{top[0][0]}' ({top[0][1]}x)." if top else "No objections recorded yet."
    return data, summary


def _intent_mix(db, tid, start, end, now):
    from app.models.call import Call
    rows = db.query(Call.intent).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
        Call.intent.isnot(None),
    ).all()
    counts: dict[str, int] = {}
    for (intent,) in rows:
        counts[intent] = counts.get(intent, 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    total = sum(counts.values())
    data = {"intents": [{"label": k, "count": v, "pct": round(v/total*100) if total else 0} for k, v in top]}
    summary = f"Top intent: '{top[0][0]}' ({round(top[0][1]/total*100) if total else 0}% of traffic)." if top else "No intent data yet."
    return data, summary


def _response_time(db, tid, start, end, now):
    # "messaging" category -- must measure chat first-response latency
    # (inbound message -> next outbound reply), not call duration.
    # _p95_seconds only ever measures Call.duration_seconds, so a tenant
    # with WhatsApp/Instagram but no calls connected yet would silently
    # read 0s here, misreading as "instant response" rather than
    # "nothing to measure."
    from app.services.message_metrics import chat_response_p95_seconds
    p95 = chat_response_p95_seconds(db, tid, start)
    data = {"p95_seconds": p95, "p95_formatted": f"{p95:.0f}s"}
    summary = f"p95 chat response time: {p95:.0f}s over last {(end-start).days} days."
    return data, summary


def _agent_leaderboard(db, tid, start, end, now):
    from app.models.user import User
    rows = db.query(
        Call.assigned_to.label("user_id"),
        func.count(Call.id).label("total"),
        func.avg(Call.ai_score).label("avg_score"),
    ).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
        Call.assigned_to.isnot(None),
    ).group_by(Call.assigned_to).order_by(func.avg(Call.ai_score).desc()).limit(5).all()
    user_ids = [r.user_id for r in rows]
    users = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    data = {"agents": [
        {"name": users.get(r.user_id, r.user_id), "calls": r.total, "avg_score": round(float(r.avg_score or 0), 1)}
        for r in rows
    ]}
    top = data["agents"][0] if data["agents"] else None
    summary = f"Top agent: {top['name']} ({top['avg_score']}/10 avg)." if top else "No agent scores yet."
    return data, summary


def _inquiry_funnel(db, tid, start, end, now):
    """Funnel across the tenant's actual pipeline_stages (Leads360 taxonomy),
    ordered by their configured `order` -- not the old fixed 5-stage enum
    sequence, which no auto-created inquiry advances through anymore
    (stage_id carries real routing; the legacy enum column stays at NEW)."""
    from app.models.pipeline_stage import PipelineStage

    stage_rows = (
        db.query(PipelineStage)
        .filter_by(tenant_id=tid)
        .order_by(PipelineStage.order)
        .all()
    )
    count_rows = (
        db.query(Inquiry.stage_id, func.count(Inquiry.id))
        .filter(Inquiry.tenant_id == tid, Inquiry.stage_id.isnot(None))
        .group_by(Inquiry.stage_id)
        .all()
    )
    counts = {r[0]: r[1] for r in count_rows}
    stages = [{"stage": s.key, "label": s.label, "count": counts.get(s.id, 0)} for s in stage_rows]
    top_count = max((s["count"] for s in stages), default=0) or 1
    for s in stages:
        s["pct"] = round(s["count"] / top_count * 100) if top_count else 0

    won = sum(counts.get(s.id, 0) for s in stage_rows if s.is_closed_won)
    total = sum(counts.values())
    cvr = round(won / total * 100, 1) if total else 0
    data = {"stages": stages, "conversion_rate": cvr}
    summary = f"{cvr}% lead-to-sold conversion rate ({won} sold / {total} total)."
    return data, summary


def _channel_mix(db, tid, start, end, now):
    from app.models.inquiry import InquirySource
    rows = db.query(Inquiry.source, func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= start,
    ).group_by(Inquiry.source).all()
    total = sum(r[1] for r in rows)
    data = {"channels": [
        {"source": r[0].value if hasattr(r[0], "value") else str(r[0]),
         "count": r[1],
         "pct": round(r[1]/total*100) if total else 0}
        for r in sorted(rows, key=lambda x: x[1], reverse=True)
    ]}
    top = data["channels"][0] if data["channels"] else None
    summary = f"Top channel: {top['source']} ({top['pct']}% of inquiries)." if top else "No channel data."
    return data, summary


def _attribution(db, tid, start, end, now):
    from app.models.inquiry import InquirySource
    from app.services.pipeline_stage_service import get_stage_ids_by_flag
    won_ids = get_stage_ids_by_flag(db, tid, is_closed_won=True)
    rows = db.query(Inquiry.source, func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage_id.in_(won_ids) if won_ids else sa_false(),
    ).group_by(Inquiry.source).all()
    total = sum(r[1] for r in rows)
    data = {"sources": [
        {"source": r[0].value if hasattr(r[0], "value") else str(r[0]),
         "booked": r[1],
         "pct": round(r[1]/total*100) if total else 0}
        for r in sorted(rows, key=lambda x: x[1], reverse=True)
    ]}
    top = data["sources"][0] if data["sources"] else None
    summary = f"Top booking source: {top['source']} ({top['pct']}% of bookings)." if top else "No booking attribution data."
    return data, summary


def _campaign_performance(db, tid, start, end, now):
    # Stub — campaigns module wired separately; return empty data with early note
    return {"campaigns": []}, "Campaign data will appear after your first WhatsApp blast."


def _guest_ltv(db, tid, start, end, now):
    rows = db.query(
        func.count(Stay.id).label("stays"),
        func.avg(Stay.total_amount).label("avg_ltv"),
        func.sum(Stay.total_amount).label("total_rev"),
    ).filter(Stay.tenant_id == tid).first()
    if not rows or not rows.stays:
        return {"stays": 0, "avg_ltv": 0, "total_rev": 0}, "No stay data yet."
    data = {
        "stays": rows.stays,
        "avg_ltv": round(float(rows.avg_ltv or 0)),
        "total_rev": round(float(rows.total_rev or 0)),
    }
    summary = f"Avg guest LTV ₹{data['avg_ltv']:,} across {data['stays']} stays."
    return data, summary


def _occupancy_forecast(db, tid, start, end, now):
    # Read from pre-computed forecasting endpoint data — simplified snapshot
    # Full data available at /analytics/forecasting/occupancy
    stays_30 = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == tid,
        Stay.check_in >= now,
        Stay.check_in <= now + timedelta(days=30),
    ).scalar() or 0
    props = db.query(func.count(Property.id)).filter(Property.tenant_id == tid).scalar() or 1
    data = {"upcoming_stays": stays_30, "property_count": props}
    summary = f"{stays_30} stays booked in next 30 days across {props} properties."
    return data, summary


def _revenue_forecast(db, tid, start, end, now):
    total = db.query(func.sum(Stay.total_amount)).filter(
        Stay.tenant_id == tid,
        Stay.check_in >= now,
        Stay.check_in <= now + timedelta(days=30),
    ).scalar() or 0
    data = {"forecast_30d": round(float(total))}
    summary = f"₹{float(total):,.0f} revenue forecasted in next 30 days."
    return data, summary


def _pricing(db, tid, start, end, now):
    return {"note": "Pricing signals require rate plan data."}, "See full pricing analysis for details."


def _churn_risk(db, tid, start, end, now):
    cutoff = now - timedelta(days=180)
    at_risk = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == tid,
        Stay.check_out <= cutoff,
    ).scalar() or 0
    data = {"at_risk_guests": at_risk}
    summary = f"{at_risk} guests haven't returned in 6+ months."
    return data, summary


def _cohorts(db, tid, start, end, now):
    total = db.query(func.count(Stay.id)).filter(Stay.tenant_id == tid).scalar() or 0
    repeat = db.query(func.count(Stay.id)).filter(
        Stay.tenant_id == tid,
        Stay.guest_id.in_(
            db.query(Stay.guest_id).filter(Stay.tenant_id == tid)
            .group_by(Stay.guest_id).having(func.count(Stay.id) > 1)
        ),
    ).scalar() or 0
    pct = round(repeat / total * 100, 1) if total else 0
    data = {"total_stays": total, "repeat_stays": repeat, "repeat_pct": pct}
    summary = f"{pct}% of stays are from returning guests."
    return data, summary


def _ai_recommendations(db, tid, start, end, now):
    from app.models.insight import Insight
    rows = db.query(Insight).filter(
        Insight.tenant_id == tid,
        Insight.dismissed_at.is_(None),
    ).order_by(Insight.severity.desc(), Insight.created_at.desc()).limit(5).all()
    data = {"recommendations": [
        {"id": str(r.id), "title": r.title, "severity": r.severity, "body": r.body}
        for r in rows
    ]}
    summary = f"{len(rows)} active AI recommendations." if rows else "No recommendations at this time."
    return data, summary


_BUILDERS = {
    "call_volume":         _call_volume,
    "sentiment":           _sentiment,
    "missed_revenue":      _missed_revenue,
    "objections":          _objections,
    "intent_mix":          _intent_mix,
    "response_time":       _response_time,
    "agent_leaderboard":   _agent_leaderboard,
    "inquiry_funnel":      _inquiry_funnel,
    "channel_mix":         _channel_mix,
    "attribution":         _attribution,
    "campaign_performance":_campaign_performance,
    "guest_ltv":           _guest_ltv,
    "occupancy_forecast":  _occupancy_forecast,
    "revenue_forecast":    _revenue_forecast,
    "pricing":             _pricing,
    "churn_risk":          _churn_risk,
    "cohorts":             _cohorts,
    "ai_recommendations":  _ai_recommendations,
}


# ─── Upsert helper ────────────────────────────────────────────────────────────

def upsert_widget(
    db: Session,
    tenant: Tenant,
    widget_key: str,
    modules: set[str],
    range_days: int = 30,
) -> DashboardWidget:
    defn = WIDGET_REGISTRY.get(widget_key)
    state = compute_widget_state(db, tenant, widget_key, modules)

    if state == "full_insight":
        data, summary = build_widget_data(db, tenant, widget_key, range_days)
        error = None
    else:
        data, summary, error = None, None, None

    now = datetime.now(timezone.utc)
    refresh_hours = defn.refresh_hours if defn else 6
    next_refresh = now + timedelta(hours=refresh_hours)

    existing = db.query(DashboardWidget).filter(
        DashboardWidget.tenant_id == tenant.id,
        DashboardWidget.widget_key == widget_key,
    ).first()

    if existing:
        existing.state = state
        existing.data = data
        existing.summary = summary
        existing.generated_at = now
        existing.next_refresh_at = next_refresh
        existing.error_message = error
        db.flush()
        return existing

    row = DashboardWidget(
        tenant_id=tenant.id,
        widget_key=widget_key,
        state=state,
        data=data,
        summary=summary,
        generated_at=now,
        next_refresh_at=next_refresh,
        error_message=error,
    )
    db.add(row)
    db.flush()
    return row
