"""Phase 2.5 agent-accountability read helpers
(HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.5).

No new schema for "who converted this lead" -- InquiryStageLog already
captures changed_by=actor_user_id|"system" on every stage transition,
through both inquiry_service.py transition paths (_apply_stage,
_apply_stage_by_id). This module just reads it.
"""
from typing import Optional

from sqlalchemy import func, Integer, cast
from sqlalchemy.orm import Session

from app.models.inquiry_360 import InquiryStageLog
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.call import Call
from app.models.task import Task
from app.models.ai_draft_outcome import AIDraftOutcome
from app.services.date_presets import ist_range_to_utc
from app.services import call_status_service
from app.models.user import User
from app.models.tenant import Tenant


def get_conversion_actor(db: Session, tenant_id: str, inquiry_id: str) -> Optional[str]:
    """
    Returns the user_id (or "system") who moved this inquiry into the
    tenant's is_closed_won stage, per the user's own definition: the agent
    assigned at the moment the inquiry's stage flipped to closed-won -- not
    whoever created the inquiry, not whoever was on the winning
    conversation thread.

    Only resolves transitions made through the current stage_id/
    pipeline_stages path (_apply_stage_by_id) -- InquiryStageLog.to_stage
    holds the PipelineStage.key for that path, but holds the legacy
    InquiryStage enum's .value for transitions made through the older
    _apply_stage path (e.g. "BOOKED"), which won't match a pipeline_stages
    key at all. Per CLAUDE.md, the legacy stage flow is being retired, so
    this is an accepted gap rather than something worth reconciling two
    different stage vocabularies for.

    Returns None if the inquiry was never closed-won, or if no matching
    stage log row exists (e.g. it happened before the log started being
    written, or the log write itself failed -- best-effort, per
    inquiry_service.py's own try/except around it).
    """
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        return None

    closed_won_stage = (
        db.query(PipelineStage)
        .filter_by(tenant_id=tenant_id, is_closed_won=True)
        .first()
    )
    if not closed_won_stage:
        return None

    log_entry = (
        db.query(InquiryStageLog)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id, to_stage=closed_won_stage.key)
        .order_by(InquiryStageLog.changed_at.asc())
        .first()
    )
    return log_entry.changed_by if log_entry else None


def get_agent_scorecard_rows(
    db: Session, tenant_id: str, date_from: str, date_to: str,
) -> list[dict]:
    """
    Role-aware dashboard rebuild: one row per active user combining every
    Phase 2.5 signal -- leads handled, response time, follow-up completion,
    calls answered + missed-callback rate, AI draft approval rate,
    conversions. Each signal is one grouped query, merged in Python by
    user_id -- deliberately not one giant multi-join (fan-out risk across
    5 unrelated tables with very different cardinalities per user).

    date_from/date_to are inclusive IST calendar-date strings (YYYY-MM-DD),
    already resolved by date_presets.resolve_range() upstream.
    """
    # ist_range_to_utc() converts the IST calendar-day boundary into the
    # correct UTC instants -- this previously built a naive
    # "{date}T00:00:00" string with no timezone conversion at all, which
    # every *.created_at/*.changed_at comparison below then interpreted as
    # UTC, shifting the window by IST's +5:30 offset (see date_presets.py).
    range_start, range_end_dt, range_start_dt, range_end_dt_obj = ist_range_to_utc(date_from, date_to)

    users = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.is_active == True, User.is_deleted == False)  # noqa: E712
        .all()
    )
    rows = {
        u.id: {
            "agent_id": u.id, "agent_name": u.name,
            "leads_handled": 0, "avg_response_seconds": 0.0, "response_count": 0,
            "followups_total": 0, "followups_completed": 0, "followups_overdue": 0,
            "calls_answered": 0, "calls_missed": 0, "calls_missed_recovered": 0,
            "ai_drafts_total": 0, "ai_drafts_approved": 0, "ai_drafts_rejected": 0,
            "conversions": 0,
        }
        for u in users
    }

    # Leads handled
    for uid, cnt in (
        db.query(Inquiry.assigned_to, func.count(Inquiry.id))
        .filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.assigned_to.isnot(None),
            Inquiry.created_at >= range_start,
            Inquiry.created_at <= range_end_dt,
        )
        .group_by(Inquiry.assigned_to)
        .all()
    ):
        if uid in rows:
            rows[uid]["leads_handled"] = cnt

    # Response time (message_metrics.chat_response_by_agent -- imported
    # locally to avoid a circular import, same pattern as elsewhere in this
    # service file's sibling endpoints)
    from app.services.message_metrics import chat_response_by_agent
    for r in chat_response_by_agent(db, tenant_id, since=range_start_dt, until=range_end_dt_obj):
        if r["agent_id"] in rows:
            rows[r["agent_id"]]["avg_response_seconds"] = r["avg_seconds"]
            rows[r["agent_id"]]["response_count"] = r["response_count"]

    # Follow-ups (tasks)
    for uid, total, completed, overdue in (
        db.query(
            Task.assigned_to,
            func.count(Task.id),
            func.sum(cast(Task.is_done, Integer)),
            func.sum(cast((Task.is_done == False) & (Task.due_date < func.now()), Integer)),  # noqa: E712
        )
        .filter(
            Task.tenant_id == tenant_id,
            Task.assigned_to.isnot(None),
            Task.created_at >= range_start,
            Task.created_at <= range_end_dt,
        )
        .group_by(Task.assigned_to)
        .all()
    ):
        if uid in rows:
            rows[uid]["followups_total"] = total
            rows[uid]["followups_completed"] = int(completed or 0)
            rows[uid]["followups_overdue"] = int(overdue or 0)

    # Calls answered/missed + recovery
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    call_q = db.query(Call).filter(
        Call.tenant_id == tenant_id,
        Call.agent_id.isnot(None),
        Call.created_at >= range_start,
        Call.created_at <= range_end_dt,
    )
    if tenant and tenant.ivr_provider:
        call_q = call_q.filter(Call.ivr_provider == tenant.ivr_provider)
    for call in call_q.all():
        if call.agent_id not in rows:
            continue
        is_missed = call_status_service.is_missed_call(call)
        if is_missed:
            rows[call.agent_id]["calls_missed"] += 1
            if call.recovered_by_call_id:
                rows[call.agent_id]["calls_missed_recovered"] += 1
        else:
            rows[call.agent_id]["calls_answered"] += 1

    # AI draft outcomes
    for uid, outcome, cnt in (
        db.query(AIDraftOutcome.actor_user_id, AIDraftOutcome.outcome, func.count(AIDraftOutcome.id))
        .filter(
            AIDraftOutcome.tenant_id == tenant_id,
            AIDraftOutcome.actor_user_id.isnot(None),
            AIDraftOutcome.created_at >= range_start,
            AIDraftOutcome.created_at <= range_end_dt,
        )
        .group_by(AIDraftOutcome.actor_user_id, AIDraftOutcome.outcome)
        .all()
    ):
        if uid not in rows:
            continue
        rows[uid]["ai_drafts_total"] += cnt
        if outcome in ("sent_verbatim", "sent_edited"):
            rows[uid]["ai_drafts_approved"] += cnt
        elif outcome == "rejected":
            rows[uid]["ai_drafts_rejected"] += cnt

    # Conversions (closed-won stage transitions, per get_conversion_actor's
    # own definition -- aggregated directly rather than looping per-inquiry)
    closed_won_stages = (
        db.query(PipelineStage.key)
        .filter_by(tenant_id=tenant_id, is_closed_won=True)
        .all()
    )
    closed_won_keys = [k for (k,) in closed_won_stages]
    if closed_won_keys:
        for uid, cnt in (
            db.query(InquiryStageLog.changed_by, func.count(InquiryStageLog.id))
            .filter(
                InquiryStageLog.tenant_id == tenant_id,
                InquiryStageLog.to_stage.in_(closed_won_keys),
                InquiryStageLog.changed_at >= range_start,
                InquiryStageLog.changed_at <= range_end_dt,
            )
            .group_by(InquiryStageLog.changed_by)
            .all()
        ):
            if uid in rows:
                rows[uid]["conversions"] = cnt

    return list(rows.values())
