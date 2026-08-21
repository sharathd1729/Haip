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
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.insight import Insight
from app.models.pipeline_stage import PipelineStage
from app.services import worklist_service
from app.services.date_presets import IST, ist_range_to_utc

log = structlog.get_logger()

_SEVERITY_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


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


def build_daily_report(db: Session, tenant_id: str, *, day: Optional[str] = None) -> dict:
    """Report for one IST calendar day (default: yesterday)."""
    today_ist = datetime.now(IST).date()
    target = day or (today_ist - timedelta(days=1)).isoformat()
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
    calls_missed = sum(
        1 for c in call_rows
        if c.direction == CallDirection.INBOUND and not (c.duration_seconds or 0)
    )
    missed_not_returned = (
        db.query(func.count(Call.id))
        .filter(
            Call.tenant_id == tenant_id,
            Call.direction == CallDirection.INBOUND,
            or_(Call.duration_seconds.is_(None), Call.duration_seconds == 0),
            Call.recovered_by_call_id.is_(None),
            Call.started_at >= start_iso,
        )
        .scalar()
    ) or 0

    # ── The backlog (not day-scoped -- this is "right now") ──────────────
    # hours=None means all time: an owner's "how many are waiting on us"
    # must count the 14-day-old ones too, not just yesterday's.
    worklist = worklist_service.build_worklist(db, tenant_id, hours=None)
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
        for r in worklist["awaiting_reply"][:5]
    ]

    return {
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
    }
