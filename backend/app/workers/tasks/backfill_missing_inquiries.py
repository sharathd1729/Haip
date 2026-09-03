"""
Hourly safety net for the process_instagram_dm.py gate fix (commit b72565e):
creates the Inquiry that should already exist for any Instagram conversation
with a real, substantive first inbound message but no inquiry_id.

Confirmed live before the gate fix: process_instagram_dm.py gated
lead-auto-create on is_new_conversation (true exactly once, on the
conversation's literal first message) -- a guest whose opener didn't
qualify (a shared post/reel, an attachment) got no inquiry created, and
never got one on any later message either, no matter what they said.
321 real Ratha leads across 7 weeks were affected before the fix and the
one-off backfill script (backfill_missing_ig_inquiries.py) caught up.

This task exists because that fix is new and unproven at scale -- if a
different, not-yet-understood path still leaves a conversation without an
inquiry_id, this catches it within the hour instead of it silently
accumulating again. Cheap to run: after the one-off backfill, there
should be ~zero qualifying rows most hours.

Same routing as a live message would get -- inquiry_service.
get_or_create_from_chat() (collab-keyword match -> collab stage; phone in
text -> valid lead entry stage; otherwise -> default/invalid entry
stage), tenant-agnostic (every tenant with affected conversations, not
just Ratha).
"""
from __future__ import annotations
import logging
from celery import shared_task
from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection

logger = logging.getLogger(__name__)


def _first_qualifying_message(db, conversation_id: str, tenant_id: str):
    """Earliest inbound message with real, substantive text -- mirrors the
    exact `body and not body.startswith("[")` check process_instagram_dm.py
    applies live. Returns (body, created_at) so the caller can backdate the
    inquiry to when the guest actually said this, not whenever this sweep
    happened to run."""
    rows = (
        db.query(Message.body, Message.created_at)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    for body, created_at in rows:
        if body and not body.startswith("["):
            return body, created_at
    return None, None


@shared_task(name="backfill_missing_instagram_inquiries")
def backfill_missing_instagram_inquiries() -> dict:
    """Sweep every tenant's Instagram conversations for a missing
    inquiry_id with real text to route from, and create it."""
    from app.services.inquiry_service import get_or_create_from_chat
    from app.models.inquiry import InquirySource

    db = SessionLocal()
    try:
        conversations = (
            db.query(Conversation)
            .filter(
                Conversation.channel == ChannelType.INSTAGRAM,
                Conversation.inquiry_id.is_(None),
            )
            .all()
        )
        created = 0
        for conv in conversations:
            body, message_at = _first_qualifying_message(db, conv.id, conv.tenant_id)
            if not body:
                continue
            try:
                lead_inquiry = get_or_create_from_chat(
                    db, conv.tenant_id, conv.guest_id,
                    source=InquirySource.META_IG.value, message_text=body,
                )
                conv.inquiry_id = lead_inquiry.id
                # Real bug, caught live: get_or_create_from_chat() defaults
                # created_at to "now" (correct for a live message, wrong
                # here) -- this inquiry is being created retroactively for
                # something that happened whenever the guest actually sent
                # this message, not whenever this hourly sweep happened to
                # run. Left uncorrected once already: 348 inquiries backdated
                # up to 7 weeks all landed with created_at=now, which
                # inflated every "last 24h" dashboard metric until caught.
                if message_at:
                    lead_inquiry.created_at = message_at
                    lead_inquiry.current_stage_entered_at = message_at
                db.commit()
                created += 1
            except Exception:
                db.rollback()
                logger.warning(
                    "backfill_missing_instagram_inquiry_failed",
                    exc_info=True, extra={"conversation_id": conv.id, "tenant_id": conv.tenant_id},
                )

        if created:
            logger.info("backfill_missing_instagram_inquiries_created", extra={"count": created})
        return {"scanned": len(conversations), "created": created}
    finally:
        db.close()
