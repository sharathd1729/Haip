"""
Executive Dashboard endpoint + Insights API.
Registered as a sub-router in analytics.py / router.py.

GET  /analytics/executive
GET  /analytics/insights
POST /analytics/insights/{id}/dismiss
"""

from datetime import datetime, timezone, timedelta
from datetime import date as date_cls
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException, status as http_status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_module
from app.models.user import User
from app.models.call import Call
from app.models.inquiry import Inquiry, InquiryStage
from app.models.property import Stay, Property
from app.models.conversation import Message, MessageDirection
from app.models.insight import Insight
from app.schemas.analytics import (
    ExecutiveDashboardStats, RevenueChartPoint, FunnelStage,
    ChannelMixPoint, OccupancyHeatPoint, InsightItem, InsightList,
)
from app.core.cache import cache_key, get_cached, set_cached

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _month_bounds(now: datetime):
    """Return (first_of_month, now, first_of_prev_month, first_of_month)."""
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_first = first.replace(month=first.month - 1) if first.month > 1 \
        else first.replace(year=first.year - 1, month=12)
    return first, now, prev_first, first


def _occ_nights(db, tid, prop_ids, start, end):
    """Occupied nights across all properties (or filtered) within [start, end)."""
    q = db.query(Stay.check_in, Stay.check_out).filter(
        Stay.tenant_id == tid,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.check_in < end.date().isoformat(),
        Stay.check_out > start.date().isoformat(),
    )
    if prop_ids:
        q = q.filter(Stay.property_id.in_(prop_ids))
    total = 0
    for r in q.all():
        try:
            ci = date_cls.fromisoformat(r.check_in)
            co = date_cls.fromisoformat(r.check_out)
            s = max(ci, start.date())
            e = min(co, end.date())
            total += max(0, (e - s).days)
        except Exception:
            pass
    return total


def _occ_nights_prop(db, tid, prop_id, start, end):
    """Occupied nights for a single property."""
    q = db.query(Stay.check_in, Stay.check_out).filter(
        Stay.tenant_id == tid,
        Stay.property_id == prop_id,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.check_in < end.date().isoformat(),
        Stay.check_out > start.date().isoformat(),
    )
    total = 0
    for r in q.all():
        try:
            ci = date_cls.fromisoformat(r.check_in)
            co = date_cls.fromisoformat(r.check_out)
            s = max(ci, start.date())
            e = min(co, end.date())
            total += max(0, (e - s).days)
        except Exception:
            pass
    return total


# ─── GET /analytics/executive ─────────────────────────────────────────────────

@router.get("/executive", response_model=ExecutiveDashboardStats)
def executive_dashboard(
    range_days: int = Query(default=30, ge=7, le=90),
    property_ids: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    """
    Executive Dashboard — 6 KPI cards + 4 chart datasets.
    Redis-cached for 5 minutes per (tenant, params).
    """
    tid = current_user.tenant_id
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tid).first()
    prop_ids: Optional[List[str]] = (
        [p.strip() for p in property_ids.split(",") if p.strip()] if property_ids else None
    )

    ck = cache_key("executive", tid, range_days=range_days, prop_ids=property_ids or "all")
    cached = get_cached(ck)
    if cached is not None:
        return ExecutiveDashboardStats(**cached)

    now = datetime.now(timezone.utc)
    mtd_start, _, prev_start, prev_end = _month_bounds(now)
    mtd_days = max(1, (now.date() - mtd_start.date()).days)
    prev_days = max(1, (prev_end.date() - prev_start.date()).days)
    period_start = now - timedelta(days=range_days)
    prev_period_start = period_start - timedelta(days=range_days)

    # ── Revenue MTD (confirmed stays) ────────────────────────────────────────
    def revenue(start, end):
        q = db.query(func.coalesce(func.sum(Stay.total_amount), 0)).filter(
            Stay.tenant_id == tid,
            Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
            Stay.check_in >= start.date().isoformat(),
            Stay.check_in < end.date().isoformat(),
        )
        if prop_ids:
            q = q.filter(Stay.property_id.in_(prop_ids))
        return float(q.scalar() or 0)

    revenue_mtd  = revenue(mtd_start, now)
    revenue_prev = revenue(prev_start, prev_end)

    # ── Occupancy % (stay nights / available) ────────────────────────────────
    prop_count_q = db.query(func.count(Property.id)).filter(
        Property.tenant_id == tid, Property.is_active == True,
    )
    if prop_ids:
        prop_count_q = prop_count_q.filter(Property.id.in_(prop_ids))
    prop_count = prop_count_q.scalar() or 1

    occ_n  = _occ_nights(db, tid, prop_ids, mtd_start, now)
    occ_pn = _occ_nights(db, tid, prop_ids, prev_start, prev_end)
    occupancy_pct  = round(occ_n  / max(1, prop_count * mtd_days)  * 100, 1)
    occupancy_prev = round(occ_pn / max(1, prop_count * prev_days) * 100, 1)

    # ── Active inquiries ──────────────────────────────────────────────────────
    ACTIVE_STAGES = [InquiryStage.NEW, InquiryStage.RESPONDING, InquiryStage.QUOTED, InquiryStage.SITE_VISIT]

    def active_inq(start):
        q = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tid,
            Inquiry.stage.in_(ACTIVE_STAGES),
            Inquiry.created_at >= start.isoformat(),
        )
        if prop_ids:
            q = q.filter(Inquiry.property_id.in_(prop_ids))
        return q.scalar() or 0

    active_inquiries      = active_inq(period_start)
    active_inquiries_prev = active_inq(prev_period_start)

    # ── QA avg score ──────────────────────────────────────────────────────────
    def qa_avg(start):
        q = db.query(func.avg(Call.ai_score)).filter(
            Call.tenant_id == tid,
            Call.ai_score.isnot(None),
            Call.started_at >= start.isoformat(),
        )
        # Calls from a disconnected IVR provider (e.g. Mcube, replaced by
        # Vobiz for Ratha) must stay out of every calls-derived executive
        # number, matching dashboard.py/widget_service.py's same filter.
        if tenant and tenant.ivr_provider:
            q = q.filter(Call.ivr_provider == tenant.ivr_provider)
        if prop_ids:
            q = q.filter(Call.property_id.in_(prop_ids))
        return round(float(q.scalar() or 0), 1)

    qa_score      = qa_avg(period_start)
    qa_score_prev = qa_avg(prev_period_start)

    # ── SLA compliance % ──────────────────────────────────────────────────────
    def sla(start):
        total = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tid,
            Inquiry.first_response_at.isnot(None),
            Inquiry.created_at >= start.isoformat(),
        ).scalar() or 0
        if total == 0:
            return 100.0
        breached = db.query(func.count(Inquiry.id)).filter(
            Inquiry.tenant_id == tid,
            Inquiry.sla_breached == True,
            Inquiry.created_at >= start.isoformat(),
        ).scalar() or 0
        return round((1 - breached / total) * 100, 1)

    sla_compliance = sla(period_start)
    sla_prev       = sla(prev_period_start)

    # ── AI draft rate % ───────────────────────────────────────────────────────
    def ai_rate(start):
        outbound = db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at >= start.isoformat(),
        ).scalar() or 0
        if outbound == 0:
            return 0.0
        ai_gen = db.query(func.count(Message.id)).filter(
            Message.tenant_id == tid,
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_ai_generated == True,
            Message.created_at >= start.isoformat(),
        ).scalar() or 0
        return round(ai_gen / outbound * 100, 1)

    ai_draft_rate = ai_rate(period_start)
    ai_draft_prev = ai_rate(prev_period_start)

    # ── Revenue chart (daily, range_days) ─────────────────────────────────────
    rev_rows = db.query(
        Stay.check_in.label("d"),
        func.sum(Stay.total_amount).label("total"),
        Stay.status,
    ).filter(
        Stay.tenant_id == tid,
        Stay.check_in >= period_start.date().isoformat(),
        Stay.check_in <= now.date().isoformat(),
    ).group_by(Stay.check_in, Stay.status).order_by(Stay.check_in).all()

    rev_by_day: dict = {}
    for r in rev_rows:
        d = str(r.d) if r.d else "unknown"
        rv = rev_by_day.setdefault(d, {"confirmed": 0.0, "quoted": 0.0})
        if r.status in ("confirmed", "checked_in", "checked_out"):
            rv["confirmed"] += float(r.total or 0)

    inq_rev = db.query(
        func.date(Inquiry.created_at).label("d"),
        func.sum(Inquiry.quoted_amount).label("total"),
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage == InquiryStage.QUOTED,
        Inquiry.quoted_at >= period_start.isoformat(),
        Inquiry.quoted_amount.isnot(None),
    ).group_by(func.date(Inquiry.created_at)).all()
    for r in inq_rev:
        d = str(r.d) if r.d else "unknown"
        rev_by_day.setdefault(d, {"confirmed": 0.0, "quoted": 0.0})["quoted"] += float(r.total or 0)

    revenue_chart = [
        RevenueChartPoint(date=d, confirmed=v["confirmed"], quoted=v["quoted"])
        for d, v in sorted(rev_by_day.items())
    ]

    # ── Inquiry funnel ────────────────────────────────────────────────────────
    funnel_rows = db.query(
        Inquiry.stage, func.count(Inquiry.id).label("cnt"),
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= period_start.isoformat(),
    ).group_by(Inquiry.stage).all()

    total_inq = sum(r.cnt for r in funnel_rows) or 1
    # Display order for funnel
    _STAGE_ORDER = {"NEW": 1, "RESPONDING": 2, "QUOTED": 3, "SITE_VISIT": 4, "BOOKED": 5, "LOST": 6, "GHOSTED": 7}
    funnel = [
        FunnelStage(
            stage=str(r.stage.value if hasattr(r.stage, "value") else r.stage),
            count=r.cnt,
            pct=round(r.cnt / total_inq * 100, 1),
        )
        for r in sorted(funnel_rows, key=lambda x: _STAGE_ORDER.get(
            x.stage.value if hasattr(x.stage, "value") else str(x.stage), 99
        ))
    ]

    # ── Channel mix ───────────────────────────────────────────────────────────
    ch_rows = db.query(
        Inquiry.source, func.count(Inquiry.id).label("cnt"),
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= period_start.isoformat(),
        Inquiry.source.isnot(None),
    ).group_by(Inquiry.source).order_by(func.count(Inquiry.id).desc()).limit(8).all()

    total_ch = sum(r.cnt for r in ch_rows) or 1
    channel_mix = [
        ChannelMixPoint(
            source=str(r.source.value if hasattr(r.source, "value") else r.source),
            count=r.cnt,
            pct=round(r.cnt / total_ch * 100, 1),
        )
        for r in ch_rows
    ]

    # ── Occupancy heatmap (per property) ─────────────────────────────────────
    props_q = db.query(Property).filter(Property.tenant_id == tid, Property.is_active == True)
    if prop_ids:
        props_q = props_q.filter(Property.id.in_(prop_ids))
    all_props = props_q.limit(50).all()

    occ_heat = []
    for p in all_props:
        n = _occ_nights_prop(db, tid, str(p.id), mtd_start, now)
        occ_heat.append(OccupancyHeatPoint(
            property_id=str(p.id),
            property_name=p.name,
            pct=min(round(n / max(1, mtd_days) * 100, 1), 100.0),
        ))
    occ_heat.sort(key=lambda x: x.pct, reverse=True)

    result = ExecutiveDashboardStats(
        revenue_mtd=revenue_mtd,
        revenue_mtd_prev=revenue_prev,
        occupancy_pct=occupancy_pct,
        occupancy_prev=occupancy_prev,
        active_inquiries=active_inquiries,
        active_inquiries_prev=active_inquiries_prev,
        qa_avg_score=qa_score,
        qa_prev=qa_score_prev,
        sla_compliance_pct=sla_compliance,
        sla_prev=sla_prev,
        ai_draft_rate_pct=ai_draft_rate,
        ai_draft_prev=ai_draft_prev,
        revenue_chart=revenue_chart,
        funnel=funnel,
        channel_mix=channel_mix,
        occupancy_heatmap=occ_heat,
    )
    set_cached(ck, result.model_dump(), ttl=300)
    return result


# ─── GET /analytics/insights ─────────────────────────────────────────────────

@router.get("/insights", response_model=InsightList)
def list_insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    """Active (non-dismissed, non-resolved) insights for the tenant, severity-sorted."""
    tid = current_user.tenant_id
    rows = db.query(Insight).filter(
        Insight.tenant_id == tid,
        Insight.is_dismissed == False,
        Insight.is_auto_resolved == False,
    ).limit(10).all()

    _SEV = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    rows.sort(key=lambda r: _SEV.get(r.severity, 0), reverse=True)

    items = [
        InsightItem(
            id=r.id,
            category_code=r.category_code,
            category=r.category,
            severity=r.severity,
            title=r.title,
            body=r.body,
            cta_label=r.cta_label,
            cta_href=r.cta_href,
            detected_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    return InsightList(items=items, total=len(items))


# ─── POST /analytics/insights/{insight_id}/dismiss ───────────────────────────

@router.post("/insights/{insight_id}/dismiss")
def dismiss_insight(
    insight_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dismiss an insight for the current user."""
    row = db.query(Insight).filter(
        Insight.id == insight_id,
        Insight.tenant_id == current_user.tenant_id,
    ).first()
    if not row:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Insight not found")
    row.is_dismissed = True
    row.dismissed_by = current_user.id
    row.dismissed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "dismissed"}
