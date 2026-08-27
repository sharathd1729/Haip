"""Daily owner report — what happened yesterday, and what needs attention.

Built on the same queries the agent worklist uses (worklist_service), so the
email and the app can never disagree. The previous report path did the
opposite: `generate_reports._fetch_report_data` returned `{}` and every
figure coalesced to zero, while an LLM wrote a narrative over the emptiness
and the task logged success.

Numbers are computed over the IST day, matching the dashboard's date
presets -- an owner reading "yesterday" means their yesterday, not UTC's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.insight import Insight
from app.models.pipeline_stage import PipelineStage
from app.models.user import User, UserRole
from app.services import agent_analytics_service, call_status_service, worklist_service
from app.services.date_presets import IST, ist_range_to_utc

log = structlog.get_logger()

_SEVERITY_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

# How far back "still waiting on us" reaches. Deliberately not all time: the
# full standing backlog is 200+ for Ratha, most of it long-dead Instagram
# reel replies, and an owner cannot act on a fortnight-old "[ig_reel]". Five
# days keeps the number to leads that are still worth chasing.
BACKLOG_DAYS = 5

# Two sends a day, answering different questions:
#   evening (19:00 IST) -- salvage. Who arrived today and is still unanswered,
#     while it is a reasonable hour to message them.
#   morning (08:00 IST) -- planning. How yesterday closed, and what is still
#     outstanding going into today.
KIND_EVENING = "evening"
KIND_MORNING = "morning"


# Suppressed from every surface this function feeds (dashboard, analytics,
# daily report email) -- the detector still runs and upserts a row, this
# only hides it from consumption. D3 (integration health degraded) flagged
# out per explicit request: not actionable/wanted in the surfaced feed.
EXCLUDED_CATEGORY_CODES = {"D3"}


def get_active_insights(db: Session, tenant_id: str, limit: int = 5) -> list[dict]:
    """Active insights, most severe first.

    Sorts before limiting. The two existing inline copies of this query
    (dashboard_overview, analytics_executive) disagree with each other, and
    the dashboard one takes an arbitrary 4 rows and *then* sorts by severity
    -- so a critical insight outside those 4 is silently dropped.
    """
    rows = (
        db.query(Insight)
        .filter(
            Insight.tenant_id == tenant_id,
            Insight.is_dismissed.is_(False),
            Insight.is_auto_resolved.is_(False),
            Insight.category_code.notin_(EXCLUDED_CATEGORY_CODES),
        )
        .all()
    )
    rows.sort(key=lambda r: _SEVERITY_ORDER.get((r.severity or "info"), 0), reverse=True)
    return [
        {
            "severity": r.severity or "info",
            "title": r.title,
            "body": r.body,
            "category": r.category,
        }
        for r in rows[:limit]
    ]


_MAX_NOTABLE_CALLS = 3


def build_agent_block(db: Session, tenant_id: str, agent, target: str) -> Optional[dict]:
    """One agent's slice of a daily report for one IST day: scorecard,
    most notable calls (highest AI score first, so a strong or a rough call
    surfaces either way), and a short narrative. Shared by the owner
    report's per-agent section (get_agent_breakdown, looped over every
    agent) and the per-agent EOD report (one agent, sent to themselves).
    Returns None if the agent has no scorecard row (e.g. inactive)."""
    rows = agent_analytics_service.get_agent_scorecard_rows(db, tenant_id, target, target, agent_id=agent.id)
    scorecard = rows[0] if rows else None
    if not scorecard:
        return None

    _, _, range_start_dt, range_end_dt = ist_range_to_utc(target, target)
    calls = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id, Call.agent_id == agent.id,
            Call.created_at >= range_start_dt, Call.created_at <= range_end_dt,
        )
        .order_by(Call.ai_score.desc().nullslast())
        .limit(_MAX_NOTABLE_CALLS)
        .all()
    )
    narrative = agent_analytics_service.generate_agent_narrative(db, tenant_id, agent.id, target, target)
    return {
        "agent_name": agent.name,
        "scorecard": scorecard,
        "notable_calls": [
            {
                "disposition": str(getattr(c.ai_disposition, "value", c.ai_disposition) or "unclassified"),
                "summary": (c.ai_summary or "")[:200],
            }
            for c in calls
        ],
        "narrative": narrative,
    }


def get_agent_breakdown(db: Session, tenant_id: str, target: str) -> list[dict]:
    """Per-agent section for the owner report -- every non-owner/manager
    agent's build_agent_block(). Real work (an LLM call per agent) -- errors
    on any one agent must not break the rest of the report."""
    agents = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id, User.is_active.is_(True), User.is_deleted.is_(False),
            User.role.notin_([UserRole.OWNER, UserRole.MANAGER]),
        )
        .order_by(User.name)
        .all()
    )
    out = []
    for agent in agents:
        try:
            block = build_agent_block(db, tenant_id, agent, target)
            if block:
                out.append(block)
        except Exception as exc:
            log.warning("agent_breakdown_failed", tenant_id=tenant_id, agent_id=agent.id, error=str(exc))
    return out


def build_agent_daily_report(
    db: Session, tenant_id: str, agent_id: str, *, day: Optional[str] = None,
) -> Optional[dict]:
    """One agent's own end-of-day report -- same underlying data as their
    slice of the owner report (build_agent_block), for their personal EOD
    email. Covers "today" (this report always sends at end of day, unlike
    the owner report's evening/morning split). None if the agent doesn't
    exist or has no scorecard row for the day."""
    agent = db.query(User).filter_by(id=agent_id, tenant_id=tenant_id).first()
    if not agent:
        return None
    target = day or datetime.now(IST).date().isoformat()
    block = build_agent_block(db, tenant_id, agent, target)
    if not block:
        return None
    block["date"] = target
    return block


def build_daily_report(
    db: Session, tenant_id: str, *, day: Optional[str] = None, kind: str = KIND_MORNING,
) -> dict:
    """Report for one IST calendar day.

    kind=evening covers today (the day is still running); kind=morning covers
    yesterday and reports what is still outstanding going into today.
    """
    today_ist = datetime.now(IST).date()
    if day:
        target = day
    elif kind == KIND_EVENING:
        target = today_ist.isoformat()
    else:
        target = (today_ist - timedelta(days=1)).isoformat()
    start_iso, end_iso, start_dt, end_dt = ist_range_to_utc(target, target)

    # ── Messages in / out ────────────────────────────────────────────────
    def _msg_count(direction) -> int:
        return (
            db.query(func.count(Message.id))
            .filter(
                Message.tenant_id == tenant_id,
                Message.direction == direction,
                Message.is_internal.is_(False),
                Message.created_at >= start_dt,
                Message.created_at <= end_dt,
            )
            .scalar()
        ) or 0

    dms_in = _msg_count(MessageDirection.INBOUND)
    replies_out = _msg_count(MessageDirection.OUTBOUND)

    # Split inbound by channel so an owner can see where demand came from.
    by_channel = {}
    for channel, count in (
        db.query(Conversation.channel, func.count(Message.id))
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Message.is_internal.is_(False),
            Message.created_at >= start_dt,
            Message.created_at <= end_dt,
        )
        .group_by(Conversation.channel)
        .all()
    ):
        by_channel[str(getattr(channel, "value", channel)).lower()] = count

    # ── Leads ────────────────────────────────────────────────────────────
    # Only `valid`-category stages count as real leads, matching Leads360 and
    # the dashboard (CLAUDE.md: invalid/marketing stages are not leads).
    new_leads = (
        db.query(func.count(Inquiry.id))
        .filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.created_at >= start_iso,
            Inquiry.created_at <= end_iso,
            Inquiry.qualification_status != "unqualified",
        )
        .scalar()
    ) or 0

    qualified_leads = (
        db.query(func.count(Inquiry.id))
        .join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
        .filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.created_at >= start_iso,
            Inquiry.created_at <= end_iso,
            PipelineStage.category == "valid",
        )
        .scalar()
    ) or 0

    # ── Contact details captured ─────────────────────────────────────────
    shared_details = (
        db.query(func.count(func.distinct(GuestIdentity.guest_id)))
        .filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.identity_type.in_(worklist_service.CONTACT_IDENTITY_TYPES),
            GuestIdentity.first_seen_at >= start_dt,
            GuestIdentity.first_seen_at <= end_dt,
        )
        .scalar()
    ) or 0

    # ── Calls ────────────────────────────────────────────────────────────
    # started_at is a String column; ISO string comparison, never a cast.
    call_rows = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            Call.started_at >= start_iso,
            Call.started_at <= end_iso,
        )
        .all()
    )
    calls_total = len(call_rows)
    calls_missed = sum(1 for c in call_rows if call_status_service.is_missed_call(c))
    missed_not_returned = (
        db.query(func.count(Call.id))
        .filter(
            Call.tenant_id == tenant_id,
            call_status_service.missed_call_sql_filter(),
            Call.recovered_by_call_id.is_(None),
            Call.started_at >= start_iso,
        )
        .scalar()
    ) or 0

    # ── Still waiting on us ──────────────────────────────────────────────
    # Evening: only what arrived today, since the point is catching them
    # before the day ends. Morning: the last BACKLOG_DAYS, so yesterday's
    # unanswered leads carry over without dragging in dead ones.
    if kind == KIND_EVENING:
        worklist = worklist_service.build_worklist(db, tenant_id, since=start_dt, until=end_dt)
    else:
        worklist = worklist_service.build_worklist(db, tenant_id, hours=BACKLOG_DAYS * 24)
    awaiting = worklist["counts"]["awaiting_reply"]

    # Who specifically is waiting longest -- an owner wants names, not a number.
    top_waiting = [
        {
            "name": r["lead"]["name"],
            "channel": r.get("channel"),
            "waiting_minutes": r.get("waiting_minutes"),
            "message": (r.get("last_message") or "")[:120],
            "has_contact": r["lead"]["has_contact"],
        }
        for r in sorted(
            worklist["awaiting_reply"],
            key=lambda r: r.get("waiting_minutes") or 0,
            reverse=True,
        )[:5]
    ]

    return {
        "kind": kind,
        "backlog_days": BACKLOG_DAYS,
        "date": target,
        "metrics": {
            "dms_in": dms_in,
            "replies_out": replies_out,
            "by_channel": by_channel,
            "new_leads": new_leads,
            "qualified_leads": qualified_leads,
            "shared_details": shared_details,
            "calls_total": calls_total,
            "calls_missed": calls_missed,
            "missed_not_returned": missed_not_returned,
            "awaiting_reply": awaiting,
        },
        "top_waiting": top_waiting,
        "insights": get_active_insights(db, tenant_id),
        "by_agent": get_agent_breakdown(db, tenant_id, target),
    }
