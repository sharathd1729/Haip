"""Detailed per-lead report — every lead a human agent personally worked on
a given IST day, with the full breakdown the daily reports and the in-app
Lead Activity page need: intent, route, guest count, price quoted, special
requests, upsell, lead quality, close status, and the synthesized
ai_lead_analysis paragraph.

Scoped to real human involvement, not bot-only threads:
  - a WhatsApp/Instagram conversation with Conversation.human_owned=True
    where THIS agent sent an outbound message that day, or
  - a call with Call.agent_id set to this agent that day.

One card per Inquiry (a lead touched via both a call and a human-owned
chat the same day still yields exactly one card), matching Leads360's
"one inquiry = one card" rule.
"""
from __future__ import annotations

from typing import Optional

import structlog
from sqlalchemy.orm import Session, joinedload

from app.models.call import Call
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry
from app.models.user import User, UserRole
from app.services.date_presets import ist_range_to_utc

log = structlog.get_logger()

_SNIPPET_LEN = 160


def _channel_str(channel) -> str:
    return str(getattr(channel, "value", channel) or "").lower()


def _lead_status(inquiry: Inquiry) -> str:
    stage = inquiry.pipeline_stage
    if stage is not None and stage.is_closed_won:
        return "booked"
    if stage is not None and stage.is_closed_lost:
        return "lost"
    if inquiry.quoted_amount is not None:
        return "quoted"
    return "progress"


def _lead_quality(inquiry: Inquiry) -> Optional[dict]:
    """Reuses the analysis.sentiment/reply_urgency the summary task already
    writes -- no new classification, just a friendlier label for the
    report. None if the inquiry has never been summarized yet."""
    analysis = inquiry.ai_analysis or {}
    sentiment = analysis.get("sentiment")
    if not sentiment:
        return None
    label = {"positive": "hot", "neutral": "warm", "hesitant": "warm", "negative": "cold"}.get(sentiment, "warm")
    return {"label": label}


def get_agent_lead_cards(db: Session, tenant_id: str, agent: User, target: str) -> list[dict]:
    """Every lead this one agent personally worked on this IST day."""
    _, _, start_dt, end_dt = ist_range_to_utc(target, target)

    call_inquiry_ids = {
        r[0] for r in db.query(Call.inquiry_id)
        .filter(
            Call.tenant_id == tenant_id, Call.agent_id == agent.id,
            Call.inquiry_id.isnot(None),
            Call.created_at >= start_dt, Call.created_at <= end_dt,
        ).all()
    }
    chat_inquiry_ids = {
        r[0] for r in db.query(Conversation.inquiry_id)
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.human_owned.is_(True),
            Conversation.inquiry_id.isnot(None),
            Message.sender_id == agent.id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_internal.is_(False),
            Message.created_at >= start_dt, Message.created_at <= end_dt,
        ).all()
    }
    inquiry_ids = call_inquiry_ids | chat_inquiry_ids
    if not inquiry_ids:
        return []

    inquiries = (
        db.query(Inquiry)
        .options(joinedload(Inquiry.guest), joinedload(Inquiry.pipeline_stage))
        .filter(Inquiry.id.in_(inquiry_ids), Inquiry.tenant_id == tenant_id)
        .all()
    )

    # Batch-fetch each inquiry's most recent call and most recent
    # human-owned-conversation message that day, then pick whichever is
    # more recent per inquiry for the card's channel/snippet/timestamp --
    # same batch-then-map shape leads_service.py's _batch_* helpers use,
    # avoiding an N+1 per card.
    calls_by_inquiry: dict[str, Call] = {}
    for c in (
        db.query(Call)
        .filter(Call.inquiry_id.in_(inquiry_ids), Call.agent_id == agent.id,
                Call.created_at >= start_dt, Call.created_at <= end_dt)
        .order_by(Call.created_at.desc())
        .all()
    ):
        calls_by_inquiry.setdefault(c.inquiry_id, c)

    msgs_by_inquiry: dict[str, tuple[Message, Conversation]] = {}
    for msg, conv in (
        db.query(Message, Conversation)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Conversation.inquiry_id.in_(inquiry_ids), Conversation.human_owned.is_(True),
            Message.sender_id == agent.id, Message.direction == MessageDirection.OUTBOUND,
            Message.is_internal.is_(False),
            Message.created_at >= start_dt, Message.created_at <= end_dt,
        )
        .order_by(Message.created_at.desc())
        .all()
    ):
        msgs_by_inquiry.setdefault(conv.inquiry_id, (msg, conv))

    cards = []
    for inquiry in inquiries:
        call = calls_by_inquiry.get(inquiry.id)
        msg_conv = msgs_by_inquiry.get(inquiry.id)
        call_at = call.created_at if call else None
        msg_at = msg_conv[0].created_at if msg_conv else None
        use_call = call is not None and (msg_at is None or (call_at and call_at > msg_at))

        if use_call:
            channel = "call"
            snippet = (call.ai_summary or "")[:_SNIPPET_LEN]
            when = call_at
        elif msg_conv:
            channel = _channel_str(msg_conv[1].channel)
            snippet = (msg_conv[0].body or "")[:_SNIPPET_LEN]
            when = msg_at
        else:
            channel = "unknown"
            snippet = ""
            when = None

        guest = inquiry.guest
        guest_count = None
        if inquiry.adults:
            parts = [f"{inquiry.adults} adult{'s' if inquiry.adults > 1 else ''}"]
            if inquiry.children:
                parts.append(f"{inquiry.children} child{'ren' if inquiry.children > 1 else ''}")
            guest_count = " ".join(parts) if len(parts) == 1 else ", ".join(parts)

        cards.append({
            "inquiry_id": inquiry.id,
            "guest_name": guest.name if guest else "Unnamed lead",
            "channel": channel,
            "snippet": snippet,
            "when": when.isoformat() if when else None,
            "status": _lead_status(inquiry),
            "intent": (inquiry.ai_analysis or {}).get("intent"),
            "route_mentioned": inquiry.route_mentioned,
            "guest_count": guest_count,
            "quoted_amount": float(inquiry.quoted_amount) if inquiry.quoted_amount is not None else None,
            "special_requests": inquiry.special_requests,
            "upsell_offered": inquiry.upsell_offered,
            "upsell_accepted": inquiry.upsell_accepted,
            "lead_quality": _lead_quality(inquiry),
            "ai_lead_analysis": inquiry.ai_lead_analysis,
        })

    cards.sort(key=lambda c: c["when"] or "", reverse=True)
    return cards


def get_lead_activity(
    db: Session, tenant_id: str, target: str, *, agent_id: Optional[str] = None,
) -> list[dict]:
    """Lead cards for one agent, or every non-owner/manager agent, for one
    IST day. Errors on any one agent must not break the rest (matches
    daily_report_service.get_agent_breakdown's own resilience pattern)."""
    if agent_id:
        agent = db.query(User).filter_by(id=agent_id, tenant_id=tenant_id).first()
        if not agent:
            return []
        cards = get_agent_lead_cards(db, tenant_id, agent, target)
        for c in cards:
            c["agent_id"] = agent.id
            c["agent_name"] = agent.name
        return cards

    agents = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id, User.is_active.is_(True), User.is_deleted.is_(False),
            User.role.notin_([UserRole.OWNER, UserRole.MANAGER]),
        )
        .order_by(User.name)
        .all()
    )
    out: list[dict] = []
    for agent in agents:
        try:
            cards = get_agent_lead_cards(db, tenant_id, agent, target)
            for c in cards:
                c["agent_id"] = agent.id
                c["agent_name"] = agent.name
            out.extend(cards)
        except Exception as exc:
            log.warning("lead_activity_agent_failed", tenant_id=tenant_id, agent_id=agent.id, error=str(exc))
    return out
