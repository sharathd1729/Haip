"""Inbox helpers shared by the conversation list and its counts.

- guest_channels: every channel a guest has talked to us on (drives the
  channel icons under each guest's avatar in the Inbox).
- needs_reply: open conversations whose latest message is from the guest.
- counts for the Inbox filter chips (Needs reply / Unassigned / Mine),
  computed server-side over the whole inbox rather than only the page of
  conversations the client happens to have loaded.

All queries are batched and tenant-scoped; nothing here is per-row.
"""
from typing import Iterable

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Query, Session

from app.models.call import Call
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection

# Channel keys the frontend knows how to draw an icon for.
_CHANNEL_KEY = {
    ChannelType.INSTAGRAM.value: "instagram",
    ChannelType.WHATSAPP.value: "whatsapp",
    ChannelType.VOICE.value: "call",
}
# Display order under the avatar -- stable, so icons don't reshuffle.
_ORDER = ("instagram", "whatsapp", "call")

VIEWS = ("needs_reply", "unassigned", "mine")


def _channel_value(ch) -> str:
    return ch.value if hasattr(ch, "value") else str(ch)


def guest_channels(db: Session, tenant_id: str, guest_ids: Iterable[str]) -> dict[str, list[str]]:
    """{guest_id: ["instagram", "call", ...]} across all of the guest's
    conversations plus any phone call on record. Two queries total."""
    ids = list({g for g in guest_ids if g})
    if not ids:
        return {}
    found: dict[str, set[str]] = {g: set() for g in ids}

    for guest_id, channel in (
        db.query(Conversation.guest_id, Conversation.channel)
        .filter(Conversation.tenant_id == tenant_id, Conversation.guest_id.in_(ids))
        .distinct()
        .all()
    ):
        key = _CHANNEL_KEY.get(_channel_value(channel))
        if key:
            found[guest_id].add(key)

    for (guest_id,) in (
        db.query(Call.guest_id)
        .filter(Call.tenant_id == tenant_id, Call.guest_id.in_(ids))
        .distinct()
        .all()
    ):
        found[guest_id].add("call")

    return {g: [k for k in _ORDER if k in keys] for g, keys in found.items()}


def _last_in_out_subquery(db: Session, tenant_id: str):
    """Per conversation: time of the latest inbound and latest outbound
    message. Internal notes and unsent AI drafts don't count as replies --
    only something the guest actually received does (same rule as
    leads_service._batch_response_time)."""
    is_in = Message.direction == MessageDirection.INBOUND
    is_real_out = (
        (Message.direction == MessageDirection.OUTBOUND)
        & (Message.is_internal.isnot(True))
        & or_(Message.is_ai_generated.isnot(True), Message.was_approved.is_(True))
    )
    return (
        db.query(
            Message.conversation_id.label("conv_id"),
            func.max(case((is_in, Message.created_at))).label("last_in"),
            func.max(case((is_real_out, Message.created_at))).label("last_out"),
        )
        .filter(Message.tenant_id == tenant_id)
        .group_by(Message.conversation_id)
        .subquery()
    )


def apply_view(db: Session, q: Query, tenant_id: str, view: str, user_id: str) -> Query:
    """Narrow a Conversation query to one Inbox filter chip."""
    if view == "unassigned":
        return q.filter(Conversation.assigned_to.is_(None), Conversation.is_open.is_(True))
    if view == "mine":
        return q.filter(Conversation.assigned_to == user_id)
    if view == "needs_reply":
        sq = _last_in_out_subquery(db, tenant_id)
        return (
            q.join(sq, sq.c.conv_id == Conversation.id)
            .filter(
                Conversation.is_open.is_(True),
                sq.c.last_in.isnot(None),
                or_(sq.c.last_out.is_(None), sq.c.last_in > sq.c.last_out),
            )
        )
    return q


def inbox_base_query(db: Session, tenant_id: str) -> Query:
    """Same visibility as the default Inbox list: no personal-bridge threads
    (product decision -- reachable only via an explicit source filter) and
    no internal-notes pseudo-conversations."""
    return db.query(Conversation).filter(
        Conversation.tenant_id == tenant_id,
        or_(Conversation.source.is_(None), Conversation.source != "personal_bridge"),
        Conversation.channel != ChannelType.INTERNAL,
    )


def view_counts(db: Session, tenant_id: str, user_id: str) -> dict[str, int]:
    base = inbox_base_query(db, tenant_id)
    return {view: apply_view(db, base, tenant_id, view, user_id).count() for view in VIEWS}
