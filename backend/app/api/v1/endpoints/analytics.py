"""
Analytics endpoints.

GET /analytics/owner-daily          — KPI dashboard (A2: compare_to, A3: property_ids)
GET /analytics/personal-scorecard   — Per-agent scorecard
GET /analytics/lost-reasons         — Clustered lost-reason themes
GET /analytics/metrics/{key}/drill  — A1: per-metric breakdown by property/agent/hour/channel
GET /analytics/lost-reasons/{theme}/inquiries — A4: inquiries for a theme
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Float, Integer, true as sa_true, false as sa_false
from datetime import datetime, timezone, timedelta, date as date_type
from typing import List, Optional
import structlog
from pydantic import BaseModel

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles, require_module, require_flag
from app.api.v1.deps import oauth2_scheme
from app.models.user import User, UserRole
from app.models.call import Call
from app.models.inquiry import Inquiry, InquiryStage
from app.models.conversation import Message, Conversation
from app.models.guest import Guest
from app.models.property import Property
from app.schemas.analytics import (
    OwnerDailyStats, PersonalScorecard, LostReasonTheme,
    CallsWeekPoint, Objection, LostReasonThemeItem, KPIDelta,
    MetricDrillDown, DrillDownPoint, LostInquiryPage, LostInquiryRow,
    ExecutiveDashboardStats, RevenueChartPoint, FunnelStage,
    ChannelMixPoint, OccupancyHeatPoint, InsightItem, InsightList,
)
from app.services.lost_reason_service import get_lost_inquiries, cluster_themes
from app.services.anomaly_detector import get_call_anomalies
from app.models.insight import Insight
from app.models.property import Stay, Property
from app.models.conversation import Message, MessageDirection
from app.core.cache import cache_key, get_cached, set_cached

log = structlog.get_logger()
router = APIRouter(prefix="/analytics", tags=["analytics"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _date_range(days_back: int, now: datetime):
    """Return (start, end) as UTC datetimes for the last `days_back` days."""
    end = now
    start = now - timedelta(days=days_back)
    return start, end


def _calls_week_series(db: Session, tid: str, start: datetime, end: datetime,
                        property_ids: Optional[List[str]] = None) -> List[CallsWeekPoint]:
    q = db.query(
        func.date(Call.started_at).label("d"),
        func.count(Call.id).label("cnt"),
        func.coalesce(func.avg(Call.ai_score), 0.0).label("avg_score"),
    ).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
        Call.started_at < end,
    )
    if property_ids:
        q = q.filter(Call.property_id.in_(property_ids))
    rows = q.group_by("d").order_by("d").all()
    return [CallsWeekPoint(date=str(r.d), count=r.cnt, avg_score=round(float(r.avg_score), 1)) for r in rows]


def _p95_seconds(db: Session, tid: str, start: datetime, end: datetime,
                  property_ids: Optional[List[str]] = None) -> float:
    """p95 response time (seconds) — computed in Postgres to avoid OOM on large datasets."""
    q = db.query(
        func.percentile_cont(0.95).within_group(
            cast(Call.duration_seconds, Float).asc()
        )
    ).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
        Call.duration_seconds.isnot(None),
    )
    if property_ids:
        q = q.filter(Call.property_id.in_(property_ids))
    result = q.scalar()
    return float(result) if result is not None else 0.0


def _revenue_at_risk(db: Session, tid: str) -> Optional[float]:
    # Every inquiry created via the chat/call auto-create flow permanently
    # leaves the legacy Inquiry.stage enum at NEW -- resolve "lost" via
    # stage_id/pipeline_stages.is_closed_lost, not the enum.
    from app.services.pipeline_stage_service import get_stage_ids_by_flag
    lost_ids = get_stage_ids_by_flag(db, tid, is_closed_lost=True)
    if not lost_ids:
        return None
    total = db.query(func.sum(Inquiry.budget)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage_id.in_(lost_ids),
        Inquiry.budget.isnot(None),
    ).scalar()
    return float(total) if total else None


def _delta(current: float, previous: float) -> KPIDelta:
    if previous == 0:
        pct = 0.0
    else:
        pct = round((current - previous) / previous * 100, 1)
    direction = "up" if pct > 0 else ("down" if pct < 0 else "neutral")
    return KPIDelta(pct=pct, direction=direction)


# ─── GET /analytics/owner-daily ──────────────────────────────────────────────

@router.get("/owner-daily", response_model=OwnerDailyStats)
def owner_daily(
    range_days: int = Query(default=7, ge=1, le=90, description="Days to look back"),
    compare_to: str = Query(default="none", description="none | previous_period | previous_year"),
    property_ids: Optional[str] = Query(default=None, description="Comma-separated property IDs"),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("leads360")),
):
    now = datetime.now(timezone.utc)
    tid = current_user.tenant_id
    prop_ids: Optional[List[str]] = [p.strip() for p in property_ids.split(",") if p.strip()] if property_ids else None

    start, end = _date_range(range_days, now)

    # ── Current period stats ─────────────────────────────────────────────────
    calls_today = db.query(func.count(Call.id)).filter(
        Call.tenant_id == tid,
        Call.started_at >= now.date().isoformat(),
    ).scalar() or 0

    from app.services.pipeline_stage_service import get_stage_ids_by_flag
    _open_stage_ids = (
        get_stage_ids_by_flag(db, tid, is_closed_won=False, is_closed_lost=False)
    )
    today_queue = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage_id.in_(_open_stage_ids) if _open_stage_ids else sa_true(),
    ).scalar() or 0

    qa_q = db.query(func.avg(Call.ai_score)).filter(
        Call.tenant_id == tid, Call.ai_score.isnot(None),
        Call.started_at >= start,
    )
    if prop_ids:
        qa_q = qa_q.filter(Call.property_id.in_(prop_ids))
    qa_avg = float(qa_q.scalar() or 0.0)

    p95 = _p95_seconds(db, tid, start, end, prop_ids)
    calls_week = _calls_week_series(db, tid, start, end, prop_ids)
    rev_at_risk = _revenue_at_risk(db, tid)

    # Top objections — from call transcripts' objections field or inquiry lost_reason
    _lost_ids_for_objections = get_stage_ids_by_flag(db, tid, is_closed_lost=True)
    obj_rows = db.query(
        Inquiry.lost_reason,
        func.count(Inquiry.id).label("cnt"),
    ).filter(
        Inquiry.tenant_id == tid,
        Inquiry.lost_reason.isnot(None),
        Inquiry.stage_id.in_(_lost_ids_for_objections) if _lost_ids_for_objections else sa_true(),
    ).group_by(Inquiry.lost_reason).order_by(func.count(Inquiry.id).desc()).limit(5).all()
    top_objections = [Objection(text=r.lost_reason.replace("_", " ").title(), count=r.cnt) for r in obj_rows]

    # Lost reason themes
    lost = get_lost_inquiries(db, tid, days=90)
    themes_raw = cluster_themes(lost)
    lost_reason_themes = [
        LostReasonThemeItem(theme=t["reason"], count=t["count"], root_cause=None)
        for t in themes_raw
    ]

    # Occupancy: booked / (booked + lost)
    _won_ids = get_stage_ids_by_flag(db, tid, is_closed_won=True)
    booked = db.query(func.count(Inquiry.id)).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage_id.in_(_won_ids) if _won_ids else sa_false(),
        Inquiry.created_at >= start,
    ).scalar() or 0
    total_closed = booked + len(lost)
    occupancy_rate = round(booked / total_closed, 3) if total_closed > 0 else None

    # ── Comparison period ────────────────────────────────────────────────────
    deltas = None
    calls_week_prev = None
    if compare_to != "none":
        if compare_to == "previous_year":
            prev_start = start - timedelta(days=365)
            prev_end = end - timedelta(days=365)
        else:  # previous_period
            delta_secs = (end - start).total_seconds()
            prev_start = start - timedelta(seconds=delta_secs)
            prev_end = start

        prev_qa_q = db.query(func.avg(Call.ai_score)).filter(
            Call.tenant_id == tid, Call.ai_score.isnot(None),
            Call.started_at >= prev_start, Call.started_at < prev_end,
        )
        if prop_ids:
            prev_qa_q = prev_qa_q.filter(Call.property_id.in_(prop_ids))
        prev_qa = float(prev_qa_q.scalar() or 0.0)
        prev_p95 = _p95_seconds(db, tid, prev_start, prev_end, prop_ids)
        prev_calls = db.query(func.count(Call.id)).filter(
            Call.tenant_id == tid,
            Call.started_at >= prev_start, Call.started_at < prev_end,
        ).scalar() or 0

        deltas = {
            "qa_avg_score": _delta(qa_avg, prev_qa),
            "p95_response_time_seconds": _delta(p95, prev_p95),
            "calls_today": _delta(float(calls_today), float(prev_calls)),
        }
        calls_week_prev = _calls_week_series(db, tid, prev_start, prev_end, prop_ids)

    return OwnerDailyStats(
        date=now.date().isoformat(),
        today_queue=today_queue,
        calls_today=calls_today,
        p95_response_time_seconds=p95,
        qa_avg_score=qa_avg,
        occupancy_rate=occupancy_rate,
        revenue_at_risk=rev_at_risk,
        calls_week=calls_week,
        top_objections=top_objections,
        lost_reason_themes=lost_reason_themes,
        deltas=deltas,
        calls_week_prev=calls_week_prev,
    )


# ─── GET /analytics/personal-scorecard ───────────────────────────────────────

@router.get("/personal-scorecard", response_model=PersonalScorecard)
def personal_scorecard(
    period: str = Query(default="this_week"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("calls")),
):
    tid = current_user.tenant_id
    uid = current_user.id

    calls_handled = db.query(func.count(Call.id)).filter_by(tenant_id=tid, agent_id=uid).scalar() or 0
    avg_score = db.query(func.avg(Call.ai_score)).filter(
        Call.tenant_id == tid, Call.agent_id == uid, Call.ai_score.isnot(None)
    ).scalar()

    return PersonalScorecard(
        user_id=uid,
        user_name=current_user.name,
        period=period,
        calls_handled=calls_handled,
        avg_qa_score=float(avg_score) if avg_score else None,
    )


# ─── GET /analytics/lost-reasons ─────────────────────────────────────────────

@router.get("/lost-reasons", response_model=List[LostReasonTheme])
def lost_reasons(
    days: int = Query(default=90, le=365),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("leads360")),
):
    lost = get_lost_inquiries(db, current_user.tenant_id, days=days)
    themes = cluster_themes(lost)
    return [LostReasonTheme(**t) for t in themes]


# ─── GET /analytics/metrics/{metric_key}/drill  (A1) ─────────────────────────

_METRIC_META = {
    "qa_avg_score": ("QA avg score", ""),
    "p95_response_time_seconds": ("p95 response time", "s"),
    "calls_today": ("Calls", ""),
    "today_queue": ("Open queue", ""),
    "occupancy_rate": ("Occupancy rate", "%"),
    "revenue_at_risk": ("Revenue at risk", "₹"),
}


@router.get("/metrics/{metric_key}/drill", response_model=MetricDrillDown)
def metric_drill(
    metric_key: str,
    range_days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    now = datetime.now(timezone.utc)
    tid = current_user.tenant_id
    start, end = _date_range(range_days, now)

    label, unit = _METRIC_META.get(metric_key, (metric_key, ""))

    # ── By property ──────────────────────────────────────────────────────────
    prop_rows = db.query(
        Property.name.label("prop_name"),
        func.count(Call.id).label("cnt"),
        func.coalesce(func.avg(Call.ai_score), 0).label("avg_val"),
    ).join(Call, Call.property_id == Property.id, isouter=True).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
    ).group_by(Property.name).order_by(func.count(Call.id).desc()).limit(10).all()

    by_property = [
        DrillDownPoint(label=r.prop_name or "Unknown", value=round(float(r.avg_val), 1), count=r.cnt)
        for r in prop_rows
    ]

    # ── By agent ─────────────────────────────────────────────────────────────
    agent_rows = db.query(
        User.name.label("agent_name"),
        func.count(Call.id).label("cnt"),
        func.coalesce(func.avg(Call.ai_score), 0).label("avg_val"),
    ).join(User, Call.agent_id == User.id, isouter=True).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
    ).group_by(User.name).order_by(func.count(Call.id).desc()).limit(10).all()

    by_agent = [
        DrillDownPoint(label=r.agent_name or "Unknown", value=round(float(r.avg_val), 1), count=r.cnt)
        for r in agent_rows
    ]

    # ── By hour of day ────────────────────────────────────────────────────────
    hour_rows = db.query(
        func.extract("hour", Call.started_at).label("hr"),
        func.count(Call.id).label("cnt"),
        func.coalesce(func.avg(Call.ai_score), 0).label("avg_val"),
    ).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
    ).group_by("hr").order_by("hr").all()

    by_hour = [
        DrillDownPoint(label=f"{int(r.hr):02d}:00", value=round(float(r.avg_val), 1), count=r.cnt)
        for r in hour_rows
    ]

    # ── By channel ────────────────────────────────────────────────────────────
    chan_rows = db.query(
        Conversation.channel.label("ch"),
        func.count(Conversation.id).label("cnt"),
    ).filter(
        Conversation.tenant_id == tid,
        Conversation.created_at >= start,
    ).group_by(Conversation.channel).order_by(func.count(Conversation.id).desc()).all()

    by_channel = [
        DrillDownPoint(label=str(r.ch.value if hasattr(r.ch, "value") else r.ch), value=float(r.cnt), count=r.cnt)
        for r in chan_rows
    ]

    return MetricDrillDown(
        metric_key=metric_key,
        metric_label=label,
        unit=unit,
        by_property=by_property,
        by_agent=by_agent,
        by_hour=by_hour,
        by_channel=by_channel,
    )


# ─── GET /analytics/lost-reasons/{theme}/inquiries  (A4) ─────────────────────

@router.get("/anomalies")
def call_anomalies(
    range_days: int = Query(default=30, ge=7, le=90),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("calls", "analytics")),
):
    """A8: Return daily call series with anomaly annotations (z-score, direction, mean)."""
    return get_call_anomalies(db, current_user.tenant_id, range_days=range_days)


@router.get("/lost-reasons/{theme}/inquiries", response_model=LostInquiryPage)
def lost_reason_inquiries(
    theme: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, le=100),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("leads360")),
):
    tid = current_user.tenant_id
    offset = (page - 1) * per_page

    q = db.query(Inquiry).filter(
        Inquiry.tenant_id == tid,
        Inquiry.stage == InquiryStage.LOST,
    )
    # Simple theme matching: lost_reason contains theme keyword
    normalized = theme.lower().replace("-", "_").replace(" ", "_")
    q = q.filter(
        func.lower(Inquiry.lost_reason).contains(normalized.split("_")[0])
    )

    total = q.count()
    rows = q.order_by(Inquiry.created_at.desc()).offset(offset).limit(per_page).all()

    # Batch-load guests and properties to avoid N+1 queries
    guest_ids = [inq.guest_id for inq in rows if inq.guest_id]
    prop_ids_batch = [inq.property_id for inq in rows if inq.property_id]
    guests_map = {str(g.id): g for g in db.query(Guest).filter(Guest.id.in_(guest_ids)).all()} if guest_ids else {}
    props_map = {str(p.id): p for p in db.query(Property).filter(Property.id.in_(prop_ids_batch)).all()} if prop_ids_batch else {}

    items = []
    for inq in rows:
        guest = guests_map.get(str(inq.guest_id)) if inq.guest_id else None
        prop = props_map.get(str(inq.property_id)) if inq.property_id else None
        items.append(LostInquiryRow(
            id=inq.id,
            guest_name=guest.name if guest else None,
            guest_phone=guest.phone if guest else "",
            property_name=prop.name if prop else None,
            check_in=inq.check_in.isoformat() if inq.check_in else None,
            check_out=inq.check_out.isoformat() if inq.check_out else None,
            lost_reason=inq.lost_reason,
            last_contact=inq.updated_at.isoformat() if inq.updated_at else None,
            created_at=inq.created_at.isoformat(),
        ))

    return LostInquiryPage(
        theme=theme,
        total=total,
        page=page,
        per_page=per_page,
        items=items,
    )


# ─── GET /analytics/agent-leaderboard ────────────────────────────────────────

@router.get("/agent-leaderboard")
def agent_leaderboard(
    range_days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("calls")),
):
    """Top agents by QA score for the dashboard scorecard panel."""
    from app.models.user import User as UserModel
    tid = current_user.tenant_id
    start = datetime.now(timezone.utc) - timedelta(days=range_days)

    rows = db.query(
        Call.agent_id.label("user_id"),
        func.count(Call.id).label("total"),
        func.avg(Call.ai_score).label("avg_score"),
    ).filter(
        Call.tenant_id == tid,
        Call.started_at >= start,
        Call.agent_id.isnot(None),
        Call.ai_score.isnot(None),
    ).group_by(Call.agent_id).order_by(func.avg(Call.ai_score).desc()).limit(5).all()

    user_ids = [r.user_id for r in rows]
    users = {
        str(u.id): u.full_name
        for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()
    }

    agents = [
        {
            "name": users.get(str(r.user_id), "Unknown"),
            "calls": r.total,
            "avg_score": round(float(r.avg_score or 0), 1),
            "initials": "".join(w[0].upper() for w in (users.get(str(r.user_id), "?") or "?").split()[:2]),
        }
        for r in rows
    ]
    return {"agents": agents, "range_days": range_days}


# ─── AI Intelligence Reports (analytics/reports/*) ────────────────────────────

_REPORT_DOMAINS = {
    "executive": ["revenue", "occupancy", "inquiry", "channel"],
    "weekly":    ["revenue", "occupancy", "inquiry", "channel"],
    "monthly":   ["revenue", "occupancy", "inquiry", "guest", "channel", "property"],
    "property":  ["property", "occupancy"],
    "guest":     ["guest"],
    "revenue":   ["revenue", "channel"],
    "inquiry":   ["inquiry", "objection", "channel"],
}


class GenerateReportRequest(BaseModel):
    report_type: str
    range_days: int = 30
    send_email: bool = False


@router.get("/reports")
def list_ai_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("ask_haip")),
):
    """List previously generated AI intelligence reports for this workspace."""
    from app.models.ask_haip import AskHaipReport
    rows = (
        db.query(AskHaipReport)
        .filter(AskHaipReport.tenant_id == current_user.tenant_id)
        .order_by(AskHaipReport.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "reports": [
            {
                "id": r.id,
                "report_type": r.report_type,
                "title": r.title,
                "period_start": r.period_start,
                "period_end": r.period_end,
                "has_pdf": bool(r.pdf_s3_key),
                "email_sent_at": r.email_sent_at.isoformat() if r.email_sent_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/reports/generate")
async def generate_ai_report(
    body: GenerateReportRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("ask_haip")),
):
    """Generate an AI intelligence report using the Ask HAIP report engine."""
    from app.services.ask_haip_service import run_agents
    from app.services.ask_haip_reports import generate_report, save_report, send_report_email

    if body.report_type not in _REPORT_DOMAINS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown report_type. Valid: {list(_REPORT_DOMAINS)}")

    # Build base URL from request
    base_url = str(request.base_url).rstrip("/")
    domains = _REPORT_DOMAINS[body.report_type]

    raw_data, _ = await run_agents(
        domains=domains,
        token=token,
        base_url=base_url,
        range_days=body.range_days,
    )

    result = await generate_report(
        report_type=body.report_type,
        raw_data=raw_data,
        range_days=body.range_days,
    )

    saved = save_report(
        db=db,
        tenant_id=current_user.tenant_id,
        report_type=body.report_type,
        title=result["title"],
        html=result["html"],
        range_days=body.range_days,
    )

    if body.send_email and current_user.email:
        await send_report_email(
            to_email=current_user.email,
            to_name=current_user.full_name or current_user.email,
            report_type=body.report_type,
            title=result["title"],
            html=result["html"],
        )

    return {
        "id": saved.id,
        "report_type": result["report_type"],
        "title": result["title"],
        "html": result["html"],
    }


@router.get("/reports/{report_id}/html")
def get_ai_report_html(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("ask_haip")),
):
    """Fetch the HTML content of a previously generated AI report."""
    from app.models.ask_haip import AskHaipReport
    from fastapi import HTTPException
    row = (
        db.query(AskHaipReport)
        .filter(
            AskHaipReport.id == report_id,
            AskHaipReport.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"html": row.html_content, "title": row.title}
