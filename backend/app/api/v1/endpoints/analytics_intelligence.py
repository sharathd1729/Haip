"""
Phase 3: Hospitality Intelligence Analytics Endpoints

GET /analytics/intent       — Guest Intent distribution, conversion by intent, revenue by intent
GET /analytics/objections   — Objection Pareto, revenue lost, competitor mentions, trend
GET /analytics/attribution  — First-touch / last-touch revenue, journey paths, time to convert

All endpoints:
  - Require authentication (any role)
  - Accept ?range_days=30 and ?property_ids=uuid,uuid
  - Are Redis-cached for 5 minutes
  - Query EXISTING model fields — no new tables required
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.inquiry import Inquiry, InquiryStage
from app.models.call import Call
from app.models.property import Stay
from app.models.conversation import Conversation
from app.core.cache import cache_key, get_cached, set_cached
from app.services.intent_classifier import normalize_intent

from app.schemas.analytics import (
    IntentAnalyticsStats, IntentBucket, IntentTrendPoint,
    ObjectionAnalyticsStats, ObjectionCategory, CompetitorMention, ObjectionTrendPoint,
    AttributionAnalyticsStats, AttributionSourceRow, JourneyPathRow,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

# ─── Shared helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _period(range_days: int):
    now = _now()
    return now - timedelta(days=range_days), now

def _safe_pct(num: float | int, den: float | int) -> float:
    return round(num / den * 100, 1) if den else 0.0

def _fmt_date_week(dt: datetime) -> str:
    """Floor to week start (Monday)."""
    d = dt.date()
    return (d - timedelta(days=d.weekday())).isoformat()


# ─── Intent label map ─────────────────────────────────────────────────────────

_INTENT_LABEL = {
    "honeymoon":      "Honeymoon",
    "anniversary":    "Anniversary",
    "birthday":       "Birthday",
    "friends_trip":   "Friends Trip",
    "workcation":     "Workcation",
    "corporate":      "Corporate",
    "family_vacation":"Family Vacation",
    "long_stay":      "Long Stay",
    "weekend_getaway":"Weekend Getaway",
    "other":          "Other",
}

# ─── Objection category map ───────────────────────────────────────────────────

# Maps (inquiry.lost_reason + call.budget_signal patterns) → standard codes
_LR_TO_CODE = {
    "budget_mismatch":   "budget",
    "wrong_dates":       "dates",
    "weather_concern":   "weather",
    "chose_competitor":  "competition",
    "no_response":       "response_delay",
    "capacity":          "capacity",
    "couldnt_decide":    "undecided",
    "other":             "other",
    # call.lost_reason free-form strings
    "price":             "budget",
    "dates_unavailable": "dates",
    "still_comparing":   "undecided",
    "wrong_property":    "property_fit",
}

_OBJECTION_LABELS = {
    "budget":         "Budget / Price",
    "dates":          "Dates Unavailable",
    "weather":        "Weather Concern",
    "competition":    "Chose Competitor",
    "response_delay": "Response Delay",
    "capacity":       "Capacity Issue",
    "undecided":      "Couldn't Decide",
    "property_fit":   "Property Preference",
    "other":          "Other",
}


# ─── GET /analytics/intent ────────────────────────────────────────────────────

@router.get("/intent", response_model=IntentAnalyticsStats)
def intent_analytics(
    range_days: int = Query(default=30, ge=7, le=365),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Guest Intent Analytics — WHY guests travel.

    Data sources (in priority):
      1. calls.intent_tag (pre-classified, fast)
      2. calls.occasion (raw text → normalize on the fly)
      3. inquiries.intent_tag (pre-classified)
      4. inquiries.occasion (raw text → normalize on the fly)
    """
    tid = current_user.tenant_id
    prop_ids: Optional[List[str]] = (
        [p.strip() for p in property_ids.split(",") if p.strip()] if property_ids else None
    )
    ck = cache_key("intent", tid, range_days=range_days, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return IntentAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)

    # ── Gather intent from CALLS ──────────────────────────────────────────────
    call_q = db.query(
        Call.intent_tag,
        Call.occasion,
        Call.ai_disposition,
        Call.duration_seconds,
        Call.created_at,
        Call.property_id,
    ).filter(
        Call.tenant_id == tid,
        Call.created_at >= start.isoformat(),
    )
    if prop_ids:
        call_q = call_q.filter(Call.property_id.in_(prop_ids))
    calls = call_q.all()

    # ── Gather intent from INQUIRIES ──────────────────────────────────────────
    inq_q = db.query(
        Inquiry.intent_tag,
        Inquiry.occasion,
        Inquiry.stage,
        Inquiry.check_in,
        Inquiry.check_out,
        Inquiry.budget,
        Inquiry.created_at,
        Inquiry.property_id,
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= start.isoformat(),
    )
    if prop_ids:
        inq_q = inq_q.filter(Inquiry.property_id.in_(prop_ids))
    inquiries = inq_q.all()

    # ── Gather booked stay values for revenue by intent ───────────────────────
    stay_q = db.query(
        Stay.inquiry_id,
        Stay.total_amount,
        Stay.check_in,
        Stay.check_out,
    ).filter(
        Stay.tenant_id == tid,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.created_at >= start.isoformat(),
    )
    if prop_ids:
        stay_q = stay_q.filter(Stay.property_id.in_(prop_ids))

    stay_by_inq: dict[str, tuple[float, float]] = {}  # inquiry_id → (amount, nights)
    for s in stay_q.all():
        try:
            # migration 071: Stay.check_in/check_out are real DATE columns
            # now -- Inquiry.check_in/check_out below are untouched, still
            # String, still need fromisoformat().
            nights = max(0, (s.check_out - s.check_in).days)
        except Exception:
            nights = 0
        stay_by_inq[str(s.inquiry_id)] = (float(s.total_amount or 0), nights)

    # ── Build per-intent aggregates ───────────────────────────────────────────
    # {intent: {count, converted_calls, total_revenue, total_nights, inq_ids}}
    agg: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "booked": 0, "revenue": 0.0, "nights": 0, "sources": set(),
    })

    # From calls
    for c in calls:
        intent = c.intent_tag or normalize_intent(c.occasion)
        agg[intent]["count"] += 1
        if c.ai_disposition in ("booked", "BOOKED"):
            agg[intent]["booked"] += 1

    # From inquiries (may overlap with calls, but provides richer conversion data)
    for inq in inquiries:
        try:
            ci = date_cls.fromisoformat(inq.check_in) if inq.check_in else None
            co = date_cls.fromisoformat(inq.check_out) if inq.check_out else None
            nights = max(0, (co - ci).days) if ci and co else None
            weekday = ci.weekday() if ci else None
        except Exception:
            nights = weekday = None

        intent = inq.intent_tag or normalize_intent(inq.occasion, nights, weekday)
        agg[intent]["count"] += 1
        if str(inq.stage) in ("booked", "BOOKED", "InquiryStage.BOOKED"):
            agg[intent]["booked"] += 1
        # Revenue from linked stays
        stay_val, stay_nights = stay_by_inq.get(str(getattr(inq, "id", "")) or "", (0.0, 0))
        agg[intent]["revenue"] += stay_val
        agg[intent]["nights"] += stay_nights

    # Build distribution list
    total_records = sum(v["count"] for v in agg.values()) or 1
    distribution: list[IntentBucket] = []
    for intent, d in sorted(agg.items(), key=lambda x: -x[1]["count"]):
        conv_pct = _safe_pct(d["booked"], d["count"])
        avg_value = round(d["revenue"] / max(1, d["booked"]), 0) if d["booked"] else 0.0
        avg_nights = round(d["nights"] / max(1, d["booked"]), 1) if d["booked"] else 0.0
        distribution.append(IntentBucket(
            intent=intent,
            count=d["count"],
            conversion_pct=conv_pct,
            avg_booking_value=avg_value,
            avg_stay_nights=avg_nights,
            revenue=round(d["revenue"], 2),
        ))

    # KPI derivations
    top_intent = distribution[0].intent if distribution else None
    top_conv   = distribution[0].conversion_pct if distribution else 0.0
    top_rev_bucket = max(distribution, key=lambda x: x.revenue) if distribution else None

    # ── Weekly trend (group by week × intent — top 4 intents only) ───────────
    top_intents = {b.intent for b in distribution[:4]}
    trend_map: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for c in calls:
        intent = c.intent_tag or normalize_intent(c.occasion)
        if intent in top_intents:
            try:
                week = _fmt_date_week(datetime.fromisoformat(str(c.created_at).replace("Z", "+00:00")))
            except Exception:
                week = start.date().isoformat()
            trend_map[week][intent] += 1

    intent_trend: list[IntentTrendPoint] = []
    for week, intent_counts in sorted(trend_map.items()):
        for intent, count in intent_counts.items():
            intent_trend.append(IntentTrendPoint(date=week, intent=intent, count=count))

    result = IntentAnalyticsStats(
        total_classified=sum(v["count"] for v in agg.values()),
        top_intent=top_intent,
        top_intent_conversion=top_conv,
        top_revenue_intent=top_rev_bucket.intent if top_rev_bucket else None,
        top_revenue_intent_value=top_rev_bucket.revenue if top_rev_bucket else 0.0,
        avg_stay_by_top_intent=distribution[0].avg_stay_nights if distribution else 0.0,
        intent_distribution=distribution,
        intent_trend=intent_trend,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/objections ───────────────────────────────────────────────

@router.get("/objections", response_model=ObjectionAnalyticsStats)
def objection_analytics(
    range_days: int = Query(default=30, ge=7, le=365),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Objection Intelligence — WHY bookings are lost.

    Sources:
      - inquiry.lost_reason (structured enum)
      - call.lost_reason (free-form string from classify.py)
      - call.budget_signal (budget sensitivity signal)
      - call.competitor_mentioned (competitor tracking)
    """
    tid = current_user.tenant_id
    prop_ids: Optional[List[str]] = (
        [p.strip() for p in property_ids.split(",") if p.strip()] if property_ids else None
    )
    ck = cache_key("objections", tid, range_days=range_days, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return ObjectionAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)

    # ── Lost inquiries ────────────────────────────────────────────────────────
    lost_q = db.query(
        Inquiry.lost_reason,
        Inquiry.budget,
        Inquiry.created_at,
        Inquiry.property_id,
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage == InquiryStage.LOST,
        Inquiry.created_at >= start.isoformat(),
    )
    if prop_ids:
        lost_q = lost_q.filter(Inquiry.property_id.in_(prop_ids))
    lost_inqs = lost_q.all()

    # ── Calls with objection signals ──────────────────────────────────────────
    call_q = db.query(
        Call.lost_reason,
        Call.budget_signal,
        Call.competitor_mentioned,
        Call.created_at,
        Call.property_id,
    ).filter(
        Call.tenant_id == tid,
        Call.created_at >= start.isoformat(),
        # Include calls with any objection signal
    ).filter(
        (Call.lost_reason.isnot(None)) |
        (Call.budget_signal.isnot(None)) |
        (Call.competitor_mentioned.isnot(None))
    )
    if prop_ids:
        call_q = call_q.filter(Call.property_id.in_(prop_ids))
    calls = call_q.all()

    # ── Aggregate objections ──────────────────────────────────────────────────
    objection_counts: dict[str, int]   = defaultdict(int)
    objection_revenue: dict[str, float] = defaultdict(float)

    total_lost = len(lost_inqs)
    total_rev_lost = 0.0

    for inq in lost_inqs:
        raw = str(inq.lost_reason.value if hasattr(inq.lost_reason, "value") else inq.lost_reason or "other").lower()
        code = _LR_TO_CODE.get(raw, "other")
        objection_counts[code] += 1
        rev = float(inq.budget or 0)
        objection_revenue[code] += rev
        total_rev_lost += rev

    # From calls — budget signal
    for c in calls:
        if c.budget_signal:
            sig = str(c.budget_signal).lower()
            if any(kw in sig for kw in ["high", "expensive", "costly", "can you", "discount", "negotiate"]):
                objection_counts["budget"] += 1

        if c.lost_reason:
            raw = str(c.lost_reason).lower().replace(" ", "_")
            code = _LR_TO_CODE.get(raw, "other")
            objection_counts[code] += 1

    # ── Competitor mentions ───────────────────────────────────────────────────
    competitor_counts: dict[str, int] = defaultdict(int)
    for c in calls:
        if c.competitor_mentioned:
            name = str(c.competitor_mentioned).strip().title()
            if name:
                competitor_counts[name] += 1

    total_objections = sum(objection_counts.values()) or 1
    cumulative = 0.0

    objections_sorted = sorted(objection_counts.items(), key=lambda x: -x[1])
    objection_list: list[ObjectionCategory] = []
    for code, count in objections_sorted:
        pct = _safe_pct(count, total_objections)
        cumulative += pct
        objection_list.append(ObjectionCategory(
            code=code,
            label=_OBJECTION_LABELS.get(code, code.replace("_", " ").title()),
            count=count,
            pct=pct,
            revenue_lost=round(objection_revenue.get(code, 0), 2),
            cumulative_pct=round(min(cumulative, 100.0), 1),
        ))

    # Competitors
    comp_total = sum(competitor_counts.values()) or 1
    competitors = [
        CompetitorMention(name=name, count=cnt, pct=_safe_pct(cnt, comp_total))
        for name, cnt in sorted(competitor_counts.items(), key=lambda x: -x[1])[:10]
    ]

    # ── Weekly trend ──────────────────────────────────────────────────────────
    trend_map: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for inq in lost_inqs:
        try:
            week = _fmt_date_week(datetime.fromisoformat(str(inq.created_at).replace("Z", "+00:00")))
        except Exception:
            week = start.date().isoformat()
        raw = str(inq.lost_reason.value if hasattr(inq.lost_reason, "value") else inq.lost_reason or "other").lower()
        code = _LR_TO_CODE.get(raw, "other")
        bucket = code if code in ("budget", "dates", "competition") else "other"
        trend_map[week][bucket] += 1

    trend: list[ObjectionTrendPoint] = [
        ObjectionTrendPoint(
            date=week,
            budget=counts.get("budget", 0),
            dates=counts.get("dates", 0),
            competition=counts.get("competition", 0),
            other=counts.get("other", 0),
        )
        for week, counts in sorted(trend_map.items())
    ]

    top = objection_list[0] if objection_list else None
    budget_pct = _safe_pct(objection_counts.get("budget", 0), total_objections)

    result = ObjectionAnalyticsStats(
        total_lost=total_lost,
        total_revenue_lost=round(total_rev_lost, 2),
        top_objection=top.label if top else None,
        top_objection_revenue_lost=top.revenue_lost if top else 0.0,
        budget_objection_pct=budget_pct,
        competitor_mention_count=sum(competitor_counts.values()),
        objections=objection_list,
        competitors=competitors,
        trend=trend,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/attribution ──────────────────────────────────────────────

@router.get("/attribution", response_model=AttributionAnalyticsStats)
def attribution_analytics(
    range_days: int = Query(default=30, ge=7, le=365),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Attribution Analytics — where bookings come from.

    First touch  = inquiry.source  (the channel that created the inquiry)
    Last touch   = last conversation.channel before stage=BOOKED
    Journey path = first_touch_source → last_touch_channel → "Booked"

    Revenue = linked stay.total_amount for BOOKED inquiries.
    """
    tid = current_user.tenant_id
    prop_ids: Optional[List[str]] = (
        [p.strip() for p in property_ids.split(",") if p.strip()] if property_ids else None
    )
    ck = cache_key("attribution", tid, range_days=range_days, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return AttributionAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)

    # ── All inquiries in the period ───────────────────────────────────────────
    inq_q = db.query(
        Inquiry.id,
        Inquiry.source,
        Inquiry.stage,
        Inquiry.created_at,
        Inquiry.current_stage_entered_at,
        Inquiry.property_id,
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= start.isoformat(),
    )
    if prop_ids:
        inq_q = inq_q.filter(Inquiry.property_id.in_(prop_ids))
    inquiries = inq_q.all()

    # ── Booked inquiries → linked stay revenue ────────────────────────────────
    booked_ids = [
        str(inq.id) for inq in inquiries
        if str(getattr(inq.stage, "value", inq.stage)).lower() in ("booked",)
    ]

    stay_revenue: dict[str, float] = {}
    if booked_ids:
        for stay in db.query(Stay.inquiry_id, Stay.total_amount, Stay.created_at).filter(
            Stay.tenant_id == tid, Stay.inquiry_id.in_(booked_ids),
        ).all():
            stay_revenue[str(stay.inquiry_id)] = float(stay.total_amount or 0)

    # ── Last conversation channel per inquiry ─────────────────────────────────
    last_channel_per_inq: dict[str, str] = {}
    conv_q = db.query(
        Conversation.inquiry_id,
        Conversation.channel,
        Conversation.created_at,
    ).filter(
        Conversation.tenant_id == tid,
        Conversation.inquiry_id.in_([str(i.id) for i in inquiries if i.id]),
    ).order_by(Conversation.created_at.desc()).all()

    seen_inq: set[str] = set()
    for conv in conv_q:
        iid = str(conv.inquiry_id)
        if iid not in seen_inq:
            ch = str(conv.channel.value if hasattr(conv.channel, "value") else conv.channel)
            last_channel_per_inq[iid] = ch
            seen_inq.add(iid)

    # ── Build first-touch / last-touch aggregates ─────────────────────────────
    # {source: {count, converted, revenue, days_list}}
    first_touch: dict[str, dict] = defaultdict(lambda: {"count": 0, "converted": 0, "revenue": 0.0, "days": []})
    last_touch:  dict[str, dict] = defaultdict(lambda: {"count": 0, "converted": 0, "revenue": 0.0, "days": []})
    journey_counts: dict[str, dict] = defaultdict(lambda: {"count": 0, "converted": 0, "days": []})

    total_bookings = 0
    total_touchpoints = 0
    all_days: list[float] = []

    for inq in inquiries:
        iid = str(inq.id)
        source = str(inq.source.value if hasattr(inq.source, "value") else inq.source or "DIRECT").upper()
        is_booked = str(getattr(inq.stage, "value", inq.stage)).lower() in ("booked",)
        rev = stay_revenue.get(iid, 0.0)
        last_ch = last_channel_per_inq.get(iid, source)

        # Days to convert
        days = 0.0
        if is_booked and inq.current_stage_entered_at and inq.created_at:
            try:
                created = inq.created_at if not isinstance(inq.created_at, str) else datetime.fromisoformat(str(inq.created_at).replace("Z", "+00:00"))
                booked_at = inq.current_stage_entered_at if not isinstance(inq.current_stage_entered_at, str) else datetime.fromisoformat(str(inq.current_stage_entered_at).replace("Z", "+00:00"))
                days = max(0, (booked_at - created).days)
            except Exception:
                days = 0.0

        # First touch
        first_touch[source]["count"] += 1
        if is_booked:
            first_touch[source]["converted"] += 1
            first_touch[source]["revenue"] += rev
            first_touch[source]["days"].append(days)
            all_days.append(days)
            total_bookings += 1

        # Last touch
        last_touch[last_ch]["count"] += 1
        if is_booked:
            last_touch[last_ch]["converted"] += 1
            last_touch[last_ch]["revenue"] += rev

        # Journey path
        if source != last_ch:
            path = f"{source} → {last_ch}"
        else:
            path = source
        journey_counts[path]["count"] += 1
        if is_booked:
            journey_counts[path]["converted"] += 1
            journey_counts[path]["days"].append(days)

        # Touchpoint count proxy: did we have a conversation?
        if iid in last_channel_per_inq:
            total_touchpoints += 2  # at least 2 (inquiry + conversation)
        else:
            total_touchpoints += 1

    avg_touchpoints = round(total_touchpoints / max(1, len(inquiries)), 1)
    avg_days = round(sum(all_days) / max(1, len(all_days)), 1)

    # Build first-touch breakdown
    def _row(source, d):
        days_list = d["days"]
        avg_d = round(sum(days_list) / max(1, len(days_list)), 1) if days_list else 0.0
        return AttributionSourceRow(
            source=source,
            inquiries=d["count"],
            converted=d["converted"],
            conversion_pct=_safe_pct(d["converted"], d["count"]),
            revenue=round(d["revenue"], 2),
            avg_days_to_convert=avg_d,
        )

    first_rows = sorted([_row(s, d) for s, d in first_touch.items()], key=lambda x: -x.revenue)
    last_rows  = sorted([_row(ch, d) for ch, d in last_touch.items()],  key=lambda x: -x.revenue)

    # Journey paths
    path_rows: list[JourneyPathRow] = []
    for path, d in sorted(journey_counts.items(), key=lambda x: -x[1]["count"])[:10]:
        path_days = d["days"]
        avg_path_days = round(sum(path_days) / max(1, len(path_days)), 1) if path_days else 0.0
        path_rows.append(JourneyPathRow(
            path=f"{path} → Booked",
            count=d["count"],
            conversion_pct=_safe_pct(d["converted"], d["count"]),
            avg_days=avg_path_days,
        ))

    # Fastest converting channel (last touch with shortest avg_days_to_convert)
    fastest = min(last_rows, key=lambda x: x.avg_days_to_convert) if last_rows else None

    top_first = first_rows[0] if first_rows else None
    top_last  = last_rows[0]  if last_rows  else None

    result = AttributionAnalyticsStats(
        total_bookings=total_bookings,
        avg_touchpoints=avg_touchpoints,
        avg_days_to_convert=avg_days,
        top_first_touch=top_first.source if top_first else None,
        top_first_touch_revenue=top_first.revenue if top_first else 0.0,
        top_last_touch=top_last.source if top_last else None,
        top_last_touch_revenue=top_last.revenue if top_last else 0.0,
        fastest_channel=fastest.source if fastest else None,
        first_touch_breakdown=first_rows,
        last_touch_breakdown=last_rows,
        journey_paths=path_rows,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result
