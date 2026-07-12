"""
Phase 2 Analytics Section Endpoints.

GET /analytics/guests       — Guest LTV, VIP tier, geo, acquisition trend
GET /analytics/channels     — Channel delivery, response time, attribution funnel
GET /analytics/campaigns    — Campaign rates, template perf, subscriber growth
GET /analytics/properties   — Property comparison matrix (RevPAR/ADR/occupancy)
GET /analytics/operations   — Agent leaderboard, SLA compliance, integration health
GET /analytics/ai           — AI acceptance, cost trend, pipeline health

All endpoints:
  - Require authentication (any role)
  - Accept ?range_days=30 and ?property_ids=uuid,uuid
  - Are Redis-cached for 5 minutes
  - Follow the exact pattern from analytics_executive.py
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, and_, or_, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.conversation import Conversation, Message, MessageDirection, ChannelType
from app.models.call import Call
from app.models.property import Stay, Property
from app.models.integration import Integration
from app.models.score import CallScore
from app.core.cache import cache_key, get_cached, set_cached

from app.schemas.analytics import (
    GuestAnalyticsStats, LTVBucket, VIPTierRow, TopCityRow, AcquisitionPoint,
    ChannelAnalyticsStats, ChannelBreakdownRow, ResponseTimeRow, AttributionFunnelRow, VolumeTrendPoint,
    CampaignAnalyticsStats, CampaignRow, TemplatePerformanceRow, SubscriberTrendPoint,
    PropertyAnalyticsStats, PropertyMatrixRow,
    OperationsAnalyticsStats, AgentLeaderboardRow, SLATrendPoint, IntegrationHealthRow,
    AIAnalyticsStats, AIAcceptanceTrendPoint, AICostTrendPoint, AIAcceptanceByAgentRow,
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


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _prev_month_start(now: datetime) -> datetime:
    first = _month_start(now)
    if first.month == 1:
        return first.replace(year=first.year - 1, month=12)
    return first.replace(month=first.month - 1)


# ─── GET /analytics/guests ────────────────────────────────────────────────────

@router.get("/guests", response_model=GuestAnalyticsStats)
def guest_analytics(
    range_days: int = Query(default=30, ge=7, le=365),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    ck = cache_key("guests", tid, range_days=range_days, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return GuestAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)
    prev_start = start - timedelta(days=range_days)

    # KPIs
    def _count(since):
        return db.query(func.count(Guest.id)).filter(
            Guest.tenant_id == tid,
            Guest.created_at >= since.isoformat(),
        ).scalar() or 0

    total_now  = db.query(func.count(Guest.id)).filter(Guest.tenant_id == tid).scalar() or 0
    total_prev = db.query(func.count(Guest.id)).filter(
        Guest.tenant_id == tid,
        Guest.created_at < start.isoformat(),
    ).scalar() or 0
    new_now    = _count(start)
    new_prev   = _count(prev_start) - _count(start) if _count(prev_start) > new_now else 0

    repeat_now  = db.query(func.count(Guest.id)).filter(
        Guest.tenant_id == tid, Guest.total_stays >= 2,
    ).scalar() or 0
    repeat_prev = db.query(func.count(Guest.id)).filter(
        Guest.tenant_id == tid, Guest.total_stays >= 2,
        Guest.created_at < start.isoformat(),
    ).scalar() or 0

    repeat_pct      = _safe_pct(repeat_now, total_now)
    repeat_pct_prev = _safe_pct(repeat_prev, total_prev) if total_prev else 0.0

    avg_ltv_now = float(db.query(func.avg(Guest.lifetime_value)).filter(
        Guest.tenant_id == tid, Guest.lifetime_value.isnot(None),
    ).scalar() or 0)
    avg_stays_now = float(db.query(func.avg(Guest.total_stays)).filter(
        Guest.tenant_id == tid,
    ).scalar() or 0)

    # LTV distribution
    thresholds = [("≥200k", 200000), ("50-200k", 50000), ("10-50k", 10000), ("<10k", 0)]
    ltv_dist = []
    guests_with_ltv = db.query(Guest).filter(
        Guest.tenant_id == tid, Guest.lifetime_value.isnot(None),
    ).with_entities(Guest.lifetime_value).all()
    ltvs = [float(r.lifetime_value) for r in guests_with_ltv]

    buckets = {"<10k": 0, "10-50k": 0, "50-200k": 0, "≥200k": 0}
    for v in ltvs:
        if v >= 200000:   buckets["≥200k"]   += 1
        elif v >= 50000:  buckets["50-200k"] += 1
        elif v >= 10000:  buckets["10-50k"]  += 1
        else:             buckets["<10k"]    += 1
    ltv_dist = [LTVBucket(bucket=k, count=v) for k, v in buckets.items()]

    # VIP tier
    vip_rows = db.query(
        Guest.vip_tier,
        func.count(Guest.id).label("cnt"),
        func.avg(Guest.lifetime_value).label("avg_ltv"),
    ).filter(Guest.tenant_id == tid).group_by(Guest.vip_tier).all()
    vip_breakdown = [
        VIPTierRow(tier=r.vip_tier, count=r.cnt, avg_ltv=round(float(r.avg_ltv or 0), 0))
        for r in sorted(vip_rows, key=lambda x: {"platinum": 0, "gold": 1, "silver": 2}.get(x.vip_tier or "", 3))
    ]

    # Top cities
    city_rows = db.query(
        Guest.city, func.count(Guest.id).label("cnt"),
    ).filter(
        Guest.tenant_id == tid, Guest.city.isnot(None),
    ).group_by(Guest.city).order_by(func.count(Guest.id).desc()).limit(8).all()
    total_with_city = sum(r.cnt for r in city_rows) or 1
    top_cities = [
        TopCityRow(city=r.city, count=r.cnt, pct=_safe_pct(r.cnt, total_with_city))
        for r in city_rows
    ]

    # Acquisition trend (daily new guests)
    acq_rows = db.query(
        func.date(Guest.created_at).label("d"),
        func.count(Guest.id).label("cnt"),
    ).filter(
        Guest.tenant_id == tid,
        Guest.created_at >= start.isoformat(),
    ).group_by(func.date(Guest.created_at)).order_by(func.date(Guest.created_at)).all()
    acquisition_trend = [AcquisitionPoint(date=str(r.d), new_guests=r.cnt) for r in acq_rows]

    result = GuestAnalyticsStats(
        total_guests=total_now,
        total_guests_prev=total_prev,
        new_guests=new_now,
        new_guests_prev=new_prev,
        repeat_guests_pct=repeat_pct,
        repeat_guests_pct_prev=repeat_pct_prev,
        avg_ltv=round(avg_ltv_now, 0),
        avg_ltv_prev=0.0,
        avg_stays=round(avg_stays_now, 1),
        ltv_distribution=ltv_dist,
        vip_breakdown=vip_breakdown,
        top_cities=top_cities,
        acquisition_trend=acquisition_trend,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/channels ─────────────────────────────────────────────────

@router.get("/channels", response_model=ChannelAnalyticsStats)
def channel_analytics(
    range_days: int = Query(default=30, ge=7, le=90),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    ck = cache_key("channels", tid, range_days=range_days)
    if (cached := get_cached(ck)) is not None:
        return ChannelAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)
    prev_start = start - timedelta(days=range_days)

    def _msg_count(since):
        return db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.created_at >= since.isoformat(),
        ).scalar() or 0

    total_msgs      = _msg_count(start)
    total_msgs_prev = _msg_count(prev_start) - total_msgs

    # Delivery stats (outbound messages only)
    from app.models.conversation import MessageDeliveryState

    out_total = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.OUTBOUND,
        Message.created_at >= start.isoformat(),
    ).scalar() or 0

    delivered = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_state.in_(["delivered", "read"]),
        Message.created_at >= start.isoformat(),
    ).scalar() or 0

    read_count = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_state == "read",
        Message.created_at >= start.isoformat(),
    ).scalar() or 0

    ai_gen = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.OUTBOUND,
        Message.is_ai_generated == True,
        Message.created_at >= start.isoformat(),
    ).scalar() or 0
    ai_approved = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.OUTBOUND,
        Message.is_ai_generated == True,
        Message.was_approved == True,
        Message.created_at >= start.isoformat(),
    ).scalar() or 0

    delivery_rate  = _safe_pct(delivered, out_total)
    read_rate      = _safe_pct(read_count, delivered)
    ai_accept_pct  = _safe_pct(ai_approved, ai_gen)

    # Response time via conversations
    conv_rows = db.query(
        Conversation.channel,
        Conversation.first_response_at,
        Conversation.created_at,
    ).filter(
        Conversation.tenant_id == tid,
        Conversation.first_response_at.isnot(None),
        Conversation.created_at >= start.isoformat(),
    ).all()

    # Group response times by channel
    from collections import defaultdict
    ch_times: dict[str, list[float]] = defaultdict(list)
    for r in conv_rows:
        try:
            ch = str(r.channel.value if hasattr(r.channel, "value") else r.channel)
            created = datetime.fromisoformat(str(r.created_at).replace("Z", "+00:00")) if isinstance(r.created_at, str) else r.created_at
            responded = datetime.fromisoformat(str(r.first_response_at).replace("Z", "+00:00")) if isinstance(r.first_response_at, str) else r.first_response_at
            if created and responded:
                diff = (responded - created).total_seconds()
                if 0 < diff < 86400 * 7:
                    ch_times[ch].append(diff)
        except Exception:
            pass

    def _median(vals): return sorted(vals)[len(vals)//2] if vals else 0.0
    def _p95(vals): return sorted(vals)[int(len(vals)*0.95)] if vals else 0.0

    all_times = [t for times in ch_times.values() for t in times]
    avg_resp = round(_median(all_times), 0)

    response_time_by_channel = [
        ResponseTimeRow(
            channel=ch,
            median_s=round(_median(times), 0),
            p95_s=round(_p95(times), 0),
        )
        for ch, times in ch_times.items()
    ]

    # Per-channel breakdown (message counts + delivery rates)
    ch_msg_rows = db.query(
        Message.channel,
        func.count(Message.id).label("total"),
        func.sum(case((Message.delivery_state.in_(["delivered", "read"]), 1), else_=0)).label("del_cnt"),
        func.sum(case((Message.delivery_state == "read", 1), else_=0)).label("read_cnt"),
        func.sum(case((Message.is_ai_generated == True, 1), else_=0)).label("ai_cnt"),
    ).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.OUTBOUND,
        Message.created_at >= start.isoformat(),
    ).group_by(Message.channel).all()

    channel_breakdown = [
        ChannelBreakdownRow(
            channel=str(r.channel.value if hasattr(r.channel, "value") else r.channel),
            messages=r.total,
            delivered_pct=_safe_pct(r.del_cnt or 0, r.total),
            read_pct=_safe_pct(r.read_cnt or 0, r.del_cnt or 1),
            ai_gen_pct=_safe_pct(r.ai_cnt or 0, r.total),
        )
        for r in ch_msg_rows
    ]

    # Attribution funnel (inquiry source → booked)
    funnel_rows = db.query(
        Inquiry.source,
        func.count(Inquiry.id).label("total"),
        func.sum(case((Inquiry.stage == InquiryStage.BOOKED, 1), else_=0)).label("booked"),
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= start.isoformat(),
        Inquiry.source.isnot(None),
    ).group_by(Inquiry.source).order_by(func.count(Inquiry.id).desc()).limit(10).all()

    attribution_funnel = [
        AttributionFunnelRow(
            source=str(r.source.value if hasattr(r.source, "value") else r.source),
            inquiries=r.total,
            converted=r.booked or 0,
            conversion_pct=_safe_pct(r.booked or 0, r.total),
        )
        for r in funnel_rows
    ]

    # Volume trend — daily counts by channel
    vol_rows = db.query(
        func.date(Message.created_at).label("d"),
        Message.channel,
        func.count(Message.id).label("cnt"),
    ).filter(
        Message.tenant_id == tid,
        Message.created_at >= start.isoformat(),
    ).group_by(func.date(Message.created_at), Message.channel).order_by(func.date(Message.created_at)).all()

    vol_by_day: dict[str, dict] = {}
    for r in vol_rows:
        d = str(r.d)
        ch = str(r.channel.value if hasattr(r.channel, "value") else r.channel).lower()
        vol_by_day.setdefault(d, {"whatsapp": 0, "instagram": 0, "voice": 0, "webchat": 0})
        if ch in vol_by_day[d]:
            vol_by_day[d][ch] += r.cnt

    volume_trend = [
        VolumeTrendPoint(date=d, **v) for d, v in sorted(vol_by_day.items())
    ]

    result = ChannelAnalyticsStats(
        total_messages=total_msgs,
        total_messages_prev=max(0, total_msgs_prev),
        delivery_rate_pct=delivery_rate,
        delivery_rate_prev=0.0,
        read_rate_pct=read_rate,
        read_rate_prev=0.0,
        avg_response_time_s=avg_resp,
        avg_response_time_prev=0.0,
        ai_acceptance_pct=ai_accept_pct,
        ai_acceptance_prev=0.0,
        channel_breakdown=channel_breakdown,
        response_time_by_channel=response_time_by_channel,
        attribution_funnel=attribution_funnel,
        volume_trend=volume_trend,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/campaigns ────────────────────────────────────────────────

@router.get("/campaigns", response_model=CampaignAnalyticsStats)
def campaign_analytics(
    range_days: int = Query(default=30, ge=7, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    ck = cache_key("campaigns", tid, range_days=range_days)
    if (cached := get_cached(ck)) is not None:
        return CampaignAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)

    # Import messaging models
    try:
        from app.models.messaging import WACampaign, WATemplate, WASubscriber
    except ImportError:
        # Models may be in different location
        from sqlalchemy import Table, MetaData
        # Return empty if models unavailable
        result = CampaignAnalyticsStats()
        set_cached(ck, result.model_dump(), ttl=300)
        return result

    # Campaign list
    camp_rows = db.query(WACampaign).filter(
        WACampaign.tenant_id == tid,
    ).order_by(WACampaign.created_at.desc()).limit(20).all()

    campaigns = []
    total_sent = total_del = total_read = 0
    active_count = 0

    for c in camp_rows:
        s = int(c.sent_count or 0)
        d = int(c.delivered_count or 0)
        r = int(c.read_count or 0)
        f = int(c.failed_count or 0)
        total_sent += s; total_del += d; total_read += r
        stat = str(c.status.value if hasattr(c.status, "value") else c.status)
        if stat in ("scheduled", "running"):
            active_count += 1
        campaigns.append(CampaignRow(
            id=str(c.id),
            name=c.name,
            status=stat,
            sent=s, delivered=d, read=r, failed=f,
            delivery_rate=_safe_pct(d, s),
            read_rate=_safe_pct(r, d),
            scheduled_at=c.scheduled_at.isoformat() if c.scheduled_at else None,
        ))

    avg_del = _safe_pct(total_del, total_sent)
    avg_read = _safe_pct(total_read, total_del)

    # Template performance
    tmpl_rows = db.query(WATemplate).filter(WATemplate.tenant_id == tid).limit(20).all()
    template_performance = [
        TemplatePerformanceRow(
            name=t.name,
            category=str(t.category.value if hasattr(t.category, "value") else t.category),
            status=str(t.status.value if hasattr(t.status, "value") else t.status),
            times_used=0,  # would need message join for accurate count
            avg_delivery_rate=0.0,
            avg_read_rate=0.0,
        )
        for t in tmpl_rows
    ]

    # Subscriber stats
    sub_total = db.query(func.count(WASubscriber.id)).filter(
        WASubscriber.tenant_id == tid, WASubscriber.opted_in == True,
    ).scalar() or 0
    sub_prev = db.query(func.count(WASubscriber.id)).filter(
        WASubscriber.tenant_id == tid,
        WASubscriber.opted_in == True,
        WASubscriber.created_at < start.isoformat(),
    ).scalar() or 0

    # Subscriber trend
    sub_trend_rows = db.query(
        func.date(WASubscriber.opt_in_at).label("d"),
        func.count(WASubscriber.id).label("in_cnt"),
    ).filter(
        WASubscriber.tenant_id == tid,
        WASubscriber.opt_in_at >= start.isoformat(),
    ).group_by(func.date(WASubscriber.opt_in_at)).order_by(func.date(WASubscriber.opt_in_at)).all()

    running_total = sub_prev
    subscriber_trend = []
    for r in sub_trend_rows:
        running_total += r.in_cnt
        subscriber_trend.append(SubscriberTrendPoint(
            date=str(r.d), opted_in=r.in_cnt, opted_out=0, cumulative=running_total,
        ))

    result = CampaignAnalyticsStats(
        total_campaigns=len(campaigns),
        active_campaigns=active_count,
        avg_delivery_rate_pct=avg_del,
        avg_read_rate_pct=avg_read,
        subscriber_count=sub_total,
        subscriber_count_prev=sub_prev,
        campaigns=campaigns,
        template_performance=template_performance,
        subscriber_trend=subscriber_trend,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/properties ───────────────────────────────────────────────

@router.get("/properties", response_model=PropertyAnalyticsStats)
def property_analytics(
    range_days: int = Query(default=30, ge=7, le=365),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    prop_ids: Optional[List[str]] = (
        [p.strip() for p in property_ids.split(",") if p.strip()] if property_ids else None
    )
    ck = cache_key("properties_analytics", tid, range_days=range_days, pids=property_ids or "all")
    if (cached := get_cached(ck)) is not None:
        return PropertyAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)
    mtd_start = _month_start(now)
    prev_month_start = _prev_month_start(now)
    mtd_days = max(1, (now.date() - mtd_start.date()).days)
    prev_days = max(1, (mtd_start.date() - prev_month_start.date()).days)

    props_q = db.query(Property).filter(Property.tenant_id == tid, Property.is_active == True)
    if prop_ids:
        props_q = props_q.filter(Property.id.in_(prop_ids))
    all_props = props_q.all()

    def _prop_stays(prop_id, start_d, end_d):
        return db.query(Stay).filter(
            Stay.tenant_id == tid,
            Stay.property_id == prop_id,
            Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
            Stay.check_in >= start_d,
            Stay.check_in < end_d,
        ).all()

    def _occ_nights(stays, start_d, end_d):
        total = 0
        for s in stays:
            try:
                ci = date_cls.fromisoformat(s.check_in)
                co = date_cls.fromisoformat(s.check_out)
                ov_s = max(ci, start_d)
                ov_e = min(co, end_d)
                total += max(0, (ov_e - ov_s).days)
            except Exception:
                pass
        return total

    matrix = []
    total_rev_mtd = total_rev_prev = occ_num = occ_den = adr_num = adr_den = 0

    for p in all_props:
        stays_mtd  = _prop_stays(str(p.id), mtd_start.date().isoformat(), now.date().isoformat())
        stays_prev = _prop_stays(str(p.id), prev_month_start.date().isoformat(), mtd_start.date().isoformat())

        rev_mtd  = sum(float(s.total_amount or 0) for s in stays_mtd)
        rev_prev = sum(float(s.total_amount or 0) for s in stays_prev)
        total_rev_mtd  += rev_mtd
        total_rev_prev += rev_prev

        occ_n = _occ_nights(stays_mtd, mtd_start.date(), now.date())
        occ_pct = round(occ_n / max(1, mtd_days) * 100, 1)
        occ_num += occ_n; occ_den += mtd_days

        # ADR = revenue / occupied nights
        adr = round(rev_mtd / max(1, occ_n), 0) if occ_n > 0 else 0.0
        adr_num += rev_mtd; adr_den += occ_n

        # RevPAR = revenue / available nights
        revpar = round(rev_mtd / max(1, mtd_days), 0)

        # Channel source breakdown
        direct  = sum(1 for s in stays_mtd if (s.channel_source or "direct") == "direct")
        ota_cnt = len(stays_mtd) - direct
        tot     = len(stays_mtd) or 1

        matrix.append(PropertyMatrixRow(
            id=str(p.id),
            name=p.name,
            type=p.type or "villa",
            city=p.city,
            occupancy_pct=occ_pct,
            revenue_mtd=rev_mtd,
            adr=adr,
            revpar=revpar,
            total_stays=len(stays_mtd),
            direct_pct=_safe_pct(direct, tot),
            ota_pct=_safe_pct(ota_cnt, tot),
        ))

    matrix.sort(key=lambda x: x.revenue_mtd, reverse=True)
    portfolio_occ = _safe_pct(occ_num, occ_den)
    portfolio_adr = round(adr_num / max(1, adr_den), 0)

    # Prev occupancy
    prev_occ_n = sum(
        _occ_nights(
            _prop_stays(str(p.id), prev_month_start.date().isoformat(), mtd_start.date().isoformat()),
            prev_month_start.date(), mtd_start.date()
        )
        for p in all_props
    )
    portfolio_occ_prev = _safe_pct(prev_occ_n, len(all_props) * prev_days) if all_props else 0.0

    result = PropertyAnalyticsStats(
        total_properties=len(all_props),
        portfolio_occupancy=portfolio_occ,
        portfolio_occupancy_prev=portfolio_occ_prev,
        portfolio_revenue_mtd=total_rev_mtd,
        portfolio_revenue_prev=total_rev_prev,
        portfolio_adr=portfolio_adr,
        properties=matrix,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/operations ───────────────────────────────────────────────

@router.get("/operations", response_model=OperationsAnalyticsStats)
def operations_analytics(
    range_days: int = Query(default=30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    ck = cache_key("operations", tid, range_days=range_days)
    if (cached := get_cached(ck)) is not None:
        return OperationsAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)
    prev_start = start - timedelta(days=range_days)
    today_str = now.date().isoformat()

    from app.models.user import User as UserModel, UserRole

    # Team
    agents = db.query(UserModel).filter(
        UserModel.tenant_id == tid,
        UserModel.is_active == True,
        UserModel.is_deleted == False,
    ).all()

    team_size = len(agents)
    calls_today = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid,
        Call.started_at >= today_str,
    ).scalar() or 0

    # Open conversations
    open_convs = db.query(func.count(Conversation.id)).filter(
        Conversation.tenant_id == tid,
        Conversation.is_open == True,
    ).scalar() or 0

    # SLA compliance
    def _sla(since):
        total = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tid,
            Inquiry.first_response_at.isnot(None),
            Inquiry.created_at >= since.isoformat(),
        ).scalar() or 0
        if not total:
            return 100.0
        breached = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tid,
            Inquiry.sla_breached == True,
            Inquiry.created_at >= since.isoformat(),
        ).scalar() or 0
        return _safe_pct(total - breached, total)

    sla_now  = _sla(start)
    sla_prev = _sla(prev_start)

    # Avg response time (median conversation first_response)
    resp_rows = db.query(
        Conversation.first_response_at, Conversation.created_at,
    ).filter(
        Conversation.tenant_id == tid,
        Conversation.first_response_at.isnot(None),
        Conversation.created_at >= start.isoformat(),
    ).all()
    resp_times = []
    for r in resp_rows:
        try:
            cr = r.created_at if not isinstance(r.created_at, str) else datetime.fromisoformat(r.created_at.replace("Z", "+00:00"))
            fr = r.first_response_at if not isinstance(r.first_response_at, str) else datetime.fromisoformat(r.first_response_at.replace("Z", "+00:00"))
            diff = (fr - cr).total_seconds()
            if 0 < diff < 86400:
                resp_times.append(diff)
        except Exception:
            pass
    avg_resp = round(sorted(resp_times)[len(resp_times)//2] if resp_times else 0, 0)

    # Agent leaderboard — grouped aggregate queries instead of 5 queries per agent.
    agent_ids = [a.id for a in agents]
    call_stats_by_agent: dict = {}
    if agent_ids:
        call_rows = (
            db.query(
                Call.agent_id,
                func.count(Call.id),
                func.avg(case((Call.ai_score.isnot(None), Call.ai_score))),
            )
            .filter(Call.tenant_id == tid, Call.agent_id.in_(agent_ids), Call.started_at >= start.isoformat())
            .group_by(Call.agent_id)
            .all()
        )
        call_stats_by_agent = {row[0]: (row[1] or 0, float(row[2] or 0)) for row in call_rows}

    inq_stats_by_agent: dict = {}
    if agent_ids:
        inq_rows = (
            db.query(
                Inquiry.assigned_to,
                func.count(Inquiry.id),
                func.sum(case((Inquiry.first_response_at.isnot(None), 1), else_=0)),
                func.sum(case((Inquiry.sla_breached == True, 1), else_=0)),
            )
            .filter(Inquiry.tenant_id == tid, Inquiry.assigned_to.in_(agent_ids), Inquiry.created_at >= start.isoformat())
            .group_by(Inquiry.assigned_to)
            .all()
        )
        inq_stats_by_agent = {row[0]: (row[1] or 0, row[2] or 0, row[3] or 0) for row in inq_rows}

    leaderboard = []
    for agent in agents:
        calls_n, qa_avg = call_stats_by_agent.get(agent.id, (0, 0.0))
        inq_n, inq_total, inq_breach = inq_stats_by_agent.get(agent.id, (0, 0, 0))
        sla_agent = _safe_pct(inq_total - inq_breach, inq_total) if inq_total else 100.0

        leaderboard.append(AgentLeaderboardRow(
            id=str(agent.id),
            name=agent.name,
            role=str(agent.role.value if hasattr(agent.role, "value") else agent.role),
            calls_handled=calls_n,
            avg_qa_score=round(qa_avg, 1),
            inquiries_handled=inq_n,
            sla_compliance_pct=sla_agent,
            avg_response_time_s=0.0,
            last_seen_at=agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        ))
    leaderboard.sort(key=lambda x: x.avg_qa_score, reverse=True)

    # SLA trend (daily)
    sla_trend_rows = db.query(
        func.date(Inquiry.created_at).label("d"),
        func.count(Inquiry.id).label("total"),
        func.sum(case((Inquiry.sla_breached == True, 1), else_=0)).label("breached"),
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.first_response_at.isnot(None),
        Inquiry.created_at >= start.isoformat(),
    ).group_by(func.date(Inquiry.created_at)).order_by(func.date(Inquiry.created_at)).all()

    sla_trend = [
        SLATrendPoint(
            date=str(r.d),
            compliant=r.total - (r.breached or 0),
            breached=r.breached or 0,
            compliance_pct=_safe_pct(r.total - (r.breached or 0), r.total),
        )
        for r in sla_trend_rows
    ]

    # Integrations
    integrations_q = db.query(Integration).filter(Integration.tenant_id == tid).all()
    cutoff_30m = (now - timedelta(minutes=30)).isoformat()
    integrations = [
        IntegrationHealthRow(
            kind=i.kind,
            status=i.status,
            last_health_at=str(i.last_health_at) if i.last_health_at else None,
            is_healthy=(i.status == "active" and bool(i.last_health_at) and str(i.last_health_at) >= cutoff_30m),
        )
        for i in integrations_q
    ]

    result = OperationsAnalyticsStats(
        team_size=team_size,
        calls_today=calls_today,
        sla_compliance_pct=sla_now,
        sla_compliance_prev=sla_prev,
        open_conversations=open_convs,
        avg_response_time_s=avg_resp,
        avg_response_time_prev=0.0,
        agents=leaderboard,
        sla_trend=sla_trend,
        integrations=integrations,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/ai ───────────────────────────────────────────────────────

@router.get("/ai", response_model=AIAnalyticsStats)
def ai_analytics(
    range_days: int = Query(default=30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    ck = cache_key("ai_analytics", tid, range_days=range_days)
    if (cached := get_cached(ck)) is not None:
        return AIAnalyticsStats(**cached)

    now = _now()
    start, _ = _period(range_days)
    prev_start = start - timedelta(days=range_days)
    today_str = now.date().isoformat()
    mtd_start = _month_start(now)
    prev_mtd_start = _prev_month_start(now)

    from app.models.user import User as UserModel

    # AI draft acceptance
    def _drafts(since):
        return db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.is_ai_generated == True,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= since.isoformat(),
        ).scalar() or 0

    def _approved(since):
        return db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.is_ai_generated == True,
            Message.was_approved == True,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= since.isoformat(),
        ).scalar() or 0

    def _rejected(since):
        return db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.is_ai_generated == True,
            Message.was_approved == False,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= since.isoformat(),
        ).scalar() or 0

    total_drafts      = _drafts(start)
    total_drafts_prev = _drafts(prev_start)
    approved_n        = _approved(start)
    rejected_n        = _rejected(start)
    edited_n          = total_drafts - approved_n - rejected_n

    acceptance_pct  = _safe_pct(approved_n, total_drafts)
    acceptance_prev = _safe_pct(_approved(prev_start), total_drafts_prev)
    rejection_pct   = _safe_pct(rejected_n, total_drafts)
    edit_pct        = _safe_pct(max(0, edited_n), total_drafts)

    # Cost MTD
    def _cost(since, end):
        row = db.query(
            func.sum(Call.transcription_cost_usd).label("trans"),
            func.sum(Call.llm_cost_usd).label("llm"),
        ).filter(
            Call.tenant_id == tid,
            Call.created_at >= since.isoformat(),
            Call.created_at < end.isoformat(),
        ).first()
        return float(row.trans or 0), float(row.llm or 0)

    trans_mtd, llm_mtd = _cost(mtd_start, now)
    trans_prev, llm_prev = _cost(prev_mtd_start, mtd_start)
    total_cost_mtd  = trans_mtd + llm_mtd
    total_cost_prev = trans_prev + llm_prev

    calls_total = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid, Call.started_at >= start.isoformat(),
    ).scalar() or 0
    avg_cost_per_call = round(total_cost_mtd / max(1, calls_total), 4)

    # Auto-scored %
    scored = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid, Call.ai_score_status == "done",
        Call.started_at >= start.isoformat(),
    ).scalar() or 0
    calls_auto_scored_pct = _safe_pct(scored, calls_total)

    # Pipeline health
    pending_trans = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid, Call.transcription_status == "pending",
    ).scalar() or 0
    pending_score = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid, Call.ai_score_status == "pending",
    ).scalar() or 0
    done_today = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid, Call.ai_score_status == "done",
        Call.updated_at >= today_str,
    ).scalar() or 0
    failed_today = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid, Call.ai_score_status == "failed",
        Call.updated_at >= today_str,
    ).scalar() or 0

    # Acceptance trend (daily)
    trend_rows = db.query(
        func.date(Message.created_at).label("d"),
        func.count(Message.id).label("total"),
        func.sum(case((Message.was_approved == True,  1), else_=0)).label("approved"),
        func.sum(case((Message.was_approved == False, 1), else_=0)).label("rejected"),
    ).filter(
        Message.tenant_id == tid,
        Message.is_ai_generated == True,
        Message.direction == MessageDirection.OUTBOUND,
        Message.created_at >= start.isoformat(),
    ).group_by(func.date(Message.created_at)).order_by(func.date(Message.created_at)).all()

    acceptance_trend = [
        AIAcceptanceTrendPoint(
            date=str(r.d),
            approved=r.approved or 0,
            rejected=r.rejected or 0,
            edited=max(0, r.total - (r.approved or 0) - (r.rejected or 0)),
            total=r.total,
        )
        for r in trend_rows
    ]

    # Cost trend (daily from calls)
    cost_rows = db.query(
        func.date(Call.started_at).label("d"),
        func.sum(Call.transcription_cost_usd).label("trans"),
        func.sum(Call.llm_cost_usd).label("llm"),
    ).filter(
        Call.tenant_id == tid,
        Call.started_at >= start.isoformat(),
    ).group_by(func.date(Call.started_at)).order_by(func.date(Call.started_at)).all()

    cost_trend = [
        AICostTrendPoint(
            date=str(r.d),
            transcription_usd=round(float(r.trans or 0), 4),
            llm_usd=round(float(r.llm or 0), 4),
            total_usd=round(float(r.trans or 0) + float(r.llm or 0), 4),
        )
        for r in cost_rows
    ]

    # Acceptance by agent
    agents = db.query(UserModel).filter(
        UserModel.tenant_id == tid, UserModel.is_active == True, UserModel.is_deleted == False,
    ).all()
    acceptance_by_agent = []
    for agent in agents:
        agent_drafts = db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.sender_id == agent.id,
            Message.is_ai_generated == True,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= start.isoformat(),
        ).scalar() or 0
        if not agent_drafts:
            continue
        agent_approved = db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.sender_id == agent.id,
            Message.is_ai_generated == True,
            Message.was_approved == True,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= start.isoformat(),
        ).scalar() or 0
        agent_rejected = db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.sender_id == agent.id,
            Message.is_ai_generated == True,
            Message.was_approved == False,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= start.isoformat(),
        ).scalar() or 0
        acceptance_by_agent.append(AIAcceptanceByAgentRow(
            agent_name=agent.name,
            drafts=agent_drafts,
            approved=agent_approved,
            rejected=agent_rejected,
            acceptance_pct=_safe_pct(agent_approved, agent_drafts),
        ))
    acceptance_by_agent.sort(key=lambda x: x.acceptance_pct, reverse=True)

    result = AIAnalyticsStats(
        total_ai_drafts=total_drafts,
        total_ai_drafts_prev=total_drafts_prev,
        acceptance_rate_pct=acceptance_pct,
        acceptance_rate_prev=acceptance_prev,
        rejection_rate_pct=rejection_pct,
        edit_rate_pct=edit_pct,
        total_cost_mtd_usd=round(total_cost_mtd, 4),
        total_cost_prev_usd=round(total_cost_prev, 4),
        avg_cost_per_call_usd=avg_cost_per_call,
        calls_auto_scored_pct=calls_auto_scored_pct,
        pipeline_pending_transcription=pending_trans,
        pipeline_pending_scoring=pending_score,
        pipeline_done_today=done_today,
        pipeline_failed_today=failed_today,
        acceptance_trend=acceptance_trend,
        cost_trend=cost_trend,
        acceptance_by_agent=acceptance_by_agent,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result
