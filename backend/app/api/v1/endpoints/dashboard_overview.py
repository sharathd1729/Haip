"""Role-aware Analytics Dashboard (V1) -- HAIP_Agent_Analytics_Dashboard_Plan_1.md
extension, `claude-fable-5-lovely-biscuit.md` plan.

GET /dashboard/overview — the single common dashboard both owners and
agents land on. Same response shape for both roles; an agent's numbers are
scoped to themselves (assigned_to/agent_id/sender_id == current_user.id),
an owner/manager sees tenant-wide numbers plus an all-agents comparison
table. Deliberately a fresh endpoint, not a reuse of the two other
pre-existing `owner_daily` implementations (analytics.py's, gated on the
still-active "leads360" module; analytics_executive.py's, gated on
"analytics") -- both carry legacy shape/behaviour this rebuild replaces.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_module
from app.services.authz_service import require_capability
from app.models.user import User, UserRole
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.call import Call, CallDirection
from app.models.property import Stay
from app.models.conversation import Conversation, Message, MessageDirection, ChannelType
from app.models.task import Task
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.insight import Insight
from app.services.date_presets import VALID_PRESETS, resolve_range
from app.services.message_metrics import chat_response_avg_seconds
from app.services.agent_analytics_service import get_agent_scorecard_rows
from app.api.v1.endpoints.analytics import _delta

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def dashboard_overview(
    date_preset: str = Query(default="today", description="today|yesterday|this_month|last_month|last_7d|last_14d|custom"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None, description="Owner/manager only -- filter the whole page to one agent"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("analytics.read")),
    _module=Depends(require_module("analytics")),
):
    tid = current_user.tenant_id
    is_owner_view = current_user.role in (UserRole.OWNER, UserRole.MANAGER)

    if date_preset not in VALID_PRESETS:
        raise HTTPException(status_code=422, detail=f"Invalid date_preset: {date_preset}")
    try:
        d_from, d_to = resolve_range(date_preset, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
    if not d_from or not d_to:
        raise HTTPException(status_code=422, detail="date_from/date_to required for a custom range")

    # Conversation.channel is a bare SAEnum (no values_callable) -- Postgres
    # stores the Python member NAME ("WHATSAPP"), not channel's lowercase
    # .value ("whatsapp"), per message_metrics.py's own note on this exact
    # trap. Comparing against the enum member itself (not the raw query
    # string) lets SQLAlchemy serialize it the way the column actually
    # expects, instead of silently matching zero rows.
    channel_enum: Optional[ChannelType] = None
    if channel:
        try:
            channel_enum = ChannelType(channel.lower())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid channel: {channel}")

    range_start = f"{d_from}T00:00:00"
    range_end = f"{d_to}T23:59:59"
    range_start_dt = datetime.fromisoformat(range_start).replace(tzinfo=timezone.utc)
    range_end_dt = datetime.fromisoformat(range_end).replace(tzinfo=timezone.utc)

    # Agent scoping: an agent role always sees only their own data, no matter
    # what agent_id they pass. Owner/manager can optionally narrow to one
    # agent via agent_id; omitting it means tenant-wide.
    if is_owner_view:
        scope_user_id = agent_id
    else:
        scope_user_id = current_user.id

    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tid).first()
    closed_won_ids = [
        r[0] for r in db.query(PipelineStage.id).filter_by(tenant_id=tid, is_closed_won=True).all()
    ]

    def _kpi_snapshot(rs: str, re_: str, rs_dt: datetime, re_dt: datetime, dfrom: str, dto: str) -> dict:
        """One period's KPI row -- called for the current period and, for
        the "Compare: Previous Period" bar, the immediately-preceding
        equal-length period. Kept as a nested closure (not a module-level
        helper) since it needs scope_user_id/property_id/tid/tenant/
        closed_won_ids from the enclosing request."""
        inq_q = db.query(Inquiry).filter(
            Inquiry.tenant_id == tid, Inquiry.created_at >= rs, Inquiry.created_at <= re_,
        )
        if scope_user_id:
            inq_q = inq_q.filter(Inquiry.assigned_to == scope_user_id)
        if property_id:
            inq_q = inq_q.filter(Inquiry.property_id == property_id)
        total_leads = inq_q.count()

        qualified_leads = (
            inq_q.join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
            .filter(PipelineStage.category == "valid")
            .count()
        )
        conversions = inq_q.filter(Inquiry.stage_id.in_(closed_won_ids)).count() if closed_won_ids else 0
        conversion_rate = round(conversions / total_leads * 100, 1) if total_leads else 0.0

        avg_response_seconds = chat_response_avg_seconds(db, tid, since=rs_dt, until=re_dt)

        task_q = db.query(Task).filter(Task.tenant_id == tid, Task.created_at >= rs, Task.created_at <= re_)
        if scope_user_id:
            task_q = task_q.filter(Task.assigned_to == scope_user_id)
        followups_total = task_q.count()
        followups_completed = task_q.filter(Task.is_done == True).count()  # noqa: E712

        # Call.started_at is a plain String column, not a real timestamp --
        # cast(..., TIMESTAMP) blows up with InvalidDatetimeFormat on any
        # row where it's "" (empty, not NULL). Plain string comparison
        # against the ISO bound (same convention as analytics_executive.py's
        # qa_avg()/sla()) sorts "" before any real ISO date, so it's
        # naturally excluded -- no cast, no crash.
        call_q = db.query(Call).filter(Call.tenant_id == tid, Call.started_at >= rs, Call.started_at <= re_)
        if tenant and tenant.ivr_provider:
            call_q = call_q.filter(Call.ivr_provider == tenant.ivr_provider)
        if scope_user_id:
            call_q = call_q.filter(Call.agent_id == scope_user_id)
        if property_id:
            call_q = call_q.filter(Call.property_id == property_id)
        total_calls = call_q.count()

        stay_q = db.query(Stay).filter(
            Stay.tenant_id == tid,
            Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
            Stay.check_in >= dfrom, Stay.check_in <= dto,
        )
        if property_id:
            stay_q = stay_q.filter(Stay.property_id == property_id)
        bookings = stay_q.count()
        revenue = float(stay_q.with_entities(func.coalesce(func.sum(Stay.total_amount), 0)).scalar() or 0)

        return {
            "total_leads": total_leads, "qualified_leads": qualified_leads,
            "avg_response_seconds": avg_response_seconds,
            "followups_total": followups_total, "followups_completed": followups_completed,
            "calls": total_calls, "bookings": bookings,
            "conversion_rate": conversion_rate, "revenue": revenue,
        }

    kpi = _kpi_snapshot(range_start, range_end, range_start_dt, range_end_dt, d_from, d_to)

    # ── Compare: Previous Period ─────────────────────────────────────────────
    # Immediately-preceding period of the same length, per the top-nav
    # "Compare: Previous Period" control in the plan's mockup.
    period_days = (date.fromisoformat(d_to) - date.fromisoformat(d_from)).days + 1
    prev_to = date.fromisoformat(d_from) - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_days - 1)
    prev_kpi = _kpi_snapshot(
        f"{prev_from.isoformat()}T00:00:00", f"{prev_to.isoformat()}T23:59:59",
        datetime.combine(prev_from, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(prev_to, datetime.max.time(), tzinfo=timezone.utc),
        prev_from.isoformat(), prev_to.isoformat(),
    )
    kpi_deltas = {
        k: _delta(float(kpi[k]), float(prev_kpi[k])).model_dump()
        for k in ("total_leads", "qualified_leads", "avg_response_seconds", "calls", "bookings", "conversion_rate", "revenue")
    }

    # Re-derive the query objects the sections below still need (funnel/
    # communication/calls use the current period only -- previous-period
    # comparison is KPI-row-only in V1, matching the plan's scope).
    call_q = db.query(Call).filter(Call.tenant_id == tid, Call.started_at >= range_start, Call.started_at <= range_end)
    if tenant and tenant.ivr_provider:
        call_q = call_q.filter(Call.ivr_provider == tenant.ivr_provider)
    if scope_user_id:
        call_q = call_q.filter(Call.agent_id == scope_user_id)
    if property_id:
        call_q = call_q.filter(Call.property_id == property_id)
    total_calls = call_q.count()
    task_q = db.query(Task).filter(Task.tenant_id == tid, Task.created_at >= range_start, Task.created_at <= range_end)
    if scope_user_id:
        task_q = task_q.filter(Task.assigned_to == scope_user_id)

    # ── Lead funnel ───────────────────────────────────────────────────────
    funnel_q = db.query(
        PipelineStage.label, PipelineStage.order, func.count(Inquiry.id).label("cnt"),
    ).join(Inquiry, Inquiry.stage_id == PipelineStage.id).filter(
        Inquiry.tenant_id == tid,
        Inquiry.created_at >= range_start,
        Inquiry.created_at <= range_end,
    )
    if scope_user_id:
        funnel_q = funnel_q.filter(Inquiry.assigned_to == scope_user_id)
    funnel_rows = funnel_q.group_by(PipelineStage.id, PipelineStage.label, PipelineStage.order).order_by(PipelineStage.order).all()
    total_funnel = sum(r.cnt for r in funnel_rows) or 1
    funnel = [
        {"stage": r.label, "count": r.cnt, "pct": round(r.cnt / total_funnel * 100, 1)}
        for r in funnel_rows
    ]

    # ── Communication (automation coverage + AI drafts) ─────────────────────
    inbound_q = db.query(Message).join(Conversation, Conversation.id == Message.conversation_id).filter(
        Message.tenant_id == tid,
        Message.direction == MessageDirection.INBOUND,
        Message.created_at >= range_start,
        Message.created_at <= range_end,
    )
    if channel_enum:
        inbound_q = inbound_q.filter(Conversation.channel == channel_enum)
    total_inbound = inbound_q.count()
    no_response = inbound_q.filter(Message.automation_outcome == "no_match_no_response").count()

    draft_q = db.query(AIDraftOutcome).filter(
        AIDraftOutcome.tenant_id == tid,
        AIDraftOutcome.created_at >= range_start,
        AIDraftOutcome.created_at <= range_end,
    )
    if scope_user_id:
        draft_q = draft_q.filter(AIDraftOutcome.actor_user_id == scope_user_id)
    ai_drafts_total = draft_q.count()
    ai_drafts_approved = draft_q.filter(AIDraftOutcome.outcome.in_(["sent_verbatim", "sent_edited"])).count()
    ai_drafts_rejected = draft_q.filter(AIDraftOutcome.outcome == "rejected").count()

    communication = {
        "total_inbound_messages": total_inbound,
        "no_automated_response": no_response,
        "automation_coverage_pct": round((1 - no_response / total_inbound) * 100, 1) if total_inbound else 100.0,
        "ai_drafts_total": ai_drafts_total,
        "ai_drafts_approved": ai_drafts_approved,
        "ai_drafts_rejected": ai_drafts_rejected,
        "ai_draft_acceptance_pct": round(ai_drafts_approved / ai_drafts_total * 100, 1) if ai_drafts_total else 0.0,
    }

    # ── Calls section ────────────────────────────────────────────────────────
    calls_answered = calls_missed = calls_missed_recovered = 0
    for call in call_q.all():
        is_missed = call.direction == CallDirection.INBOUND and not (call.duration_seconds or 0)
        if is_missed:
            calls_missed += 1
            if call.recovered_by_call_id:
                calls_missed_recovered += 1
        else:
            calls_answered += 1
    calls_section = {
        "total": total_calls,
        "answered": calls_answered,
        "missed": calls_missed,
        "missed_recovered": calls_missed_recovered,
        "callback_rate_pct": round(calls_missed_recovered / calls_missed * 100, 1) if calls_missed else 0.0,
    }

    # ── Needs attention ──────────────────────────────────────────────────────
    needs_attention = {
        "leads_no_response": no_response,
        "missed_calls_not_recovered": calls_missed - calls_missed_recovered,
        "followups_overdue": task_q.filter(Task.is_done == False, Task.due_date < func.now()).count(),  # noqa: E712
    }

    # ── AI Intelligence (existing insight_detector output, capped) ──────────
    insight_rows = db.query(Insight).filter(
        Insight.tenant_id == tid, Insight.is_dismissed == False, Insight.is_auto_resolved == False,  # noqa: E712
    ).limit(4).all()
    _SEV = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    insight_rows.sort(key=lambda r: _SEV.get(r.severity, 0), reverse=True)
    top_insights = [
        {"id": r.id, "severity": r.severity, "title": r.title, "body": r.body, "cta_label": r.cta_label, "cta_href": r.cta_href}
        for r in insight_rows
    ]

    result = {
        "date_from": d_from, "date_to": d_to,
        "role_scope": "agent" if scope_user_id and not is_owner_view else ("agent_filtered" if scope_user_id else "owner"),
        "kpi": kpi,
        "kpi_deltas": kpi_deltas,
        "funnel": funnel,
        "communication": communication,
        "calls": calls_section,
        "needs_attention": needs_attention,
        "top_insights": top_insights,
    }

    # ── All-agents comparison table (owner/manager only, tenant-wide only
    # -- doesn't make sense combined with a single agent_id filter) ─────────
    if is_owner_view and not agent_id:
        result["agents"] = get_agent_scorecard_rows(db, tid, d_from, d_to)

    return result
