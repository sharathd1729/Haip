"""
Leads360 chat auto-create backfill -- one-time remediation for
conversations that existed BEFORE the auto-create wiring shipped
(inquiry_service.get_or_create_from_chat, wired into whatsapp.py /
process_instagram_dm.py). Auto-create only fires on a conversation's
first-ever message, gated by "is this conversation new" -- pre-existing
conversations never pass through that gate and so never got an inquiry,
even though real leads are sitting in them.

This walks every WhatsApp/Instagram guest in a tenant who has no inquiry
yet, finds their earliest inbound message across all their conversations,
and routes it through the exact same get_or_create_from_chat() logic
real-time messages use -- so a backfilled lead lands on the identical
stage (collab/valid/default) a fresh message would have landed on.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
import structlog

log = structlog.get_logger()

_CHANNEL_TO_SOURCE = {
    ChannelType.WHATSAPP: InquirySource.WA_DIRECT.value,
    ChannelType.INSTAGRAM: InquirySource.META_IG.value,
}


def backfill_tenant_leads_from_conversations(db: Session, tenant_id: str) -> dict:
    """
    Returns {"guests_processed": int, "inquiries_created": int,
             "conversations_linked": int, "guests_skipped_no_message": int}.
    Idempotent -- guests who already have an open inquiry (whether from a
    prior backfill run or real-time auto-create) are left untouched, and
    conversations that already have inquiry_id set are left untouched.
    """
    stats = {
        "guests_processed": 0, "inquiries_created": 0,
        "conversations_linked": 0, "guests_skipped_no_message": 0,
    }

    guest_ids = [
        row[0] for row in
        db.query(Conversation.guest_id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.channel.in_([ChannelType.WHATSAPP, ChannelType.INSTAGRAM]),
        )
        .distinct()
        .all()
    ]

    for guest_id in guest_ids:
        stats["guests_processed"] += 1

        closed_stages = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
        has_open_inquiry = (
            db.query(Inquiry.id)
            .filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id)
            .filter(~Inquiry.stage.in_(closed_stages))
            .first()
        )

        earliest = (
            db.query(Message, Conversation.channel)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(
                Message.tenant_id == tenant_id,
                Conversation.guest_id == guest_id,
                Conversation.channel.in_([ChannelType.WHATSAPP, ChannelType.INSTAGRAM]),
                Message.direction == MessageDirection.INBOUND,
                Message.body.isnot(None),
                Message.body != "",
            )
            .order_by(Message.created_at.asc())
            .first()
        )

        if not earliest:
            stats["guests_skipped_no_message"] += 1
            continue

        message, channel = earliest
        source = _CHANNEL_TO_SOURCE.get(channel, InquirySource.PHONE.value)

        if has_open_inquiry:
            inquiry = (
                db.query(Inquiry)
                .filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id)
                .filter(~Inquiry.stage.in_(closed_stages))
                .order_by(Inquiry.created_at.desc())
                .first()
            )
        else:
            from app.services.inquiry_service import get_or_create_from_chat
            inquiry = get_or_create_from_chat(
                db, tenant_id, guest_id, source=source, message_text=message.body,
            )
            stats["inquiries_created"] += 1
            log.info(
                "lead_backfilled_from_conversation", tenant_id=tenant_id,
                guest_id=guest_id, inquiry_id=inquiry.id, channel=channel.value,
            )

        linked = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant_id,
                Conversation.guest_id == guest_id,
                Conversation.channel.in_([ChannelType.WHATSAPP, ChannelType.INSTAGRAM]),
                Conversation.inquiry_id.is_(None),
            )
            .update({"inquiry_id": inquiry.id}, synchronize_session=False)
        )
        stats["conversations_linked"] += linked

    db.flush()
    return stats
