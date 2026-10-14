"""One person's path through HAIP: how they first got in touch, when they became a lead, which channels they used since, and the
bookings and money that came from them.

Read-only and derived from the records themselves, so it can never disagree with them:
  * first touch and identification are the values written once on the guest (identity_resolution); first touch is never overwritten
    when the person returns through another platform, and an unknown first touch is reported as "unknown", never guessed;
  * latest touch and the assisted channels are worked out from what the person actually did (their messages, inbound calls, enquiries);
  * bookings are the canonical booking records (Stay.guest_id); amounts are only filled for a viewer who may see money.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.guest_merge_event import GuestMergeEvent
from app.models.inquiry import Inquiry
from app.models.property import Stay
from app.models.stay_finance import StayPayment
from app.services import dashboard_service
from app.services.lead_metrics import CONVERSATION_CHANNEL_KEY


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def build(db: Session, tenant_id: str, guest: Guest, *, can_bookings: bool, can_revenue: bool) -> dict:
    touches: list[tuple[str, object]] = []          # (channel key, when) for each thing the person did
    counts = {"conversations": 0, "messages": 0, "calls": 0, "enquiries": 0}

    convs = db.query(Conversation.id, Conversation.channel).filter(
        Conversation.tenant_id == tenant_id, Conversation.guest_id == guest.id, Conversation.channel != ChannelType.INTERNAL).all()
    counts["conversations"] = len(convs)
    key_by_conv = {cid: CONVERSATION_CHANNEL_KEY.get(ch, "other") for cid, ch in convs}
    if key_by_conv:
        for conv_id, at in db.query(Message.conversation_id, Message.created_at).filter(
                Message.tenant_id == tenant_id, Message.conversation_id.in_(list(key_by_conv)),
                Message.direction == MessageDirection.INBOUND).all():
            touches.append((key_by_conv[conv_id], at))
            counts["messages"] += 1
    for (at,) in db.query(Call.created_at).filter(Call.tenant_id == tenant_id, Call.guest_id == guest.id,
                                                  Call.direction == CallDirection.INBOUND).all():
        touches.append(("call", at))
        counts["calls"] += 1
    for source, at in db.query(Inquiry.source, Inquiry.created_at).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest.id).all():
        raw = str(getattr(source, "value", source) or "")
        touches.append((dashboard_service._SOURCE_GROUPS.get(raw, ("other", "Other"))[0], at))
        counts["enquiries"] += 1

    by_channel: dict[str, dict] = defaultdict(lambda: {"interactions": 0, "latest_at": None})
    for key, at in touches:
        slot = by_channel[key]
        slot["interactions"] += 1
        if at is not None and (slot["latest_at"] is None or at > slot["latest_at"]):
            slot["latest_at"] = at
    latest = max(((at, key) for key, at in touches if at is not None), default=None, key=lambda t: t[0])

    out = {
        "guest_id": guest.id,
        "is_lead": guest.lead_identified_at is not None,
        "identified_at": _iso(guest.lead_identified_at), "identified_via": guest.lead_identified_via,
        "first_touch": {"channel": guest.first_touch_channel or "unknown", "at": _iso(guest.first_touch_at)},
        "latest_touch": {"channel": latest[1], "at": _iso(latest[0])} if latest else None,
        "channels": sorted(({"channel": k, "interactions": v["interactions"], "latest_at": _iso(v["latest_at"])} for k, v in by_channel.items()),
                           key=lambda r: -r["interactions"]),
        **counts,
        "merged_from": [e.deprecated_id for e in db.query(GuestMergeEvent).filter(
            GuestMergeEvent.tenant_id == tenant_id, GuestMergeEvent.survivor_id == guest.id,
            GuestMergeEvent.unmerged_at.is_(None)).all()],
        "bookings": None, "paid": None,
    }
    if can_bookings:
        stays = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.guest_id == guest.id).order_by(Stay.created_at.desc()).all()
        out["bookings"] = [{"id": s.id, "status": s.status, "check_in": s.check_in.isoformat(), "check_out": s.check_out.isoformat(),
                            "total": float(s.total_amount) if (can_revenue and s.total_amount is not None) else None} for s in stays]
        if can_revenue and stays:
            paid = db.query(func.coalesce(func.sum(StayPayment.amount), 0)).filter(
                StayPayment.tenant_id == tenant_id, StayPayment.stay_id.in_([s.id for s in stays]), StayPayment.kind == "payment").scalar()
            refunded = db.query(func.coalesce(func.sum(StayPayment.amount), 0)).filter(
                StayPayment.tenant_id == tenant_id, StayPayment.stay_id.in_([s.id for s in stays]), StayPayment.kind == "refund").scalar()
            out["paid"] = float(paid or 0) - float(refunded or 0)
        elif can_revenue:
            out["paid"] = 0.0
    return out
