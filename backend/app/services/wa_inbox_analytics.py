"""WhatsApp inbox analytics (WhatsApp step 4): first-response time, conversations per team member, and cost.

First response reuses the one shared definition (impact_metrics.first_replies, KPI ``replies.first_response``), read
for the official WhatsApp channel. Conversations per person = distinct conversations where that person sent at least
one non-internal WhatsApp message in the period. Cost = wa_costs.period_cost (Meta's pricing x the workspace's rates).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

PERIODS = (7, 14, 30, 90)


def report(db: Session, tenant, days: int, *, now: datetime | None = None) -> dict:
    from app.models.conversation import ChannelType, Message, MessageDirection
    from app.models.user import User
    from app.services import impact_metrics, wa_costs

    end = now or datetime.now(UTC)
    start = end - timedelta(days=days)
    replies = impact_metrics.first_replies(db, tenant, start, end, now=end)
    wa = replies["by_channel"].get("whatsapp_cloud") or {}

    rows = (
        db.query(Message.sender_id, func.count(func.distinct(Message.conversation_id)), func.count(Message.id))
        .filter(Message.tenant_id == tenant.id, Message.channel == ChannelType.WHATSAPP,
                Message.direction == MessageDirection.OUTBOUND, Message.sender_id.isnot(None),
                Message.is_internal.isnot(True), Message.created_at >= start, Message.created_at <= end)
        .group_by(Message.sender_id).all()
    )
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant.id, User.id.in_([r[0] for r in rows] or [""])))
    people = sorted(({"user_id": uid, "name": names.get(uid) or "Former team member", "conversations": convs, "messages": msgs}
                     for uid, convs, msgs in rows), key=lambda p: -p["conversations"])

    cost = wa_costs.period_cost(db, tenant, start, end)
    return {
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "first_response": {
            "turns": wa.get("turns", 0), "answered_pct": wa.get("answered_pct"),
            "median_seconds": wa.get("median_seconds"), "p90_seconds": wa.get("p90_seconds"),
            "within_pct": wa.get("within_pct", {}),
            "by_responder": replies["by_responder"],
        },
        "people": people,
        "cost": cost,
    }
