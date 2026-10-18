"""A phone number the guest types in a chat message becomes their phone signal.

Instagram has no phone identity of its own (and a personal-WhatsApp chat seen only as an internal @lid id has none either), so a
number the guest writes in a message is the only way HAIP learns it. One place does the whole job, for the live message path and
for the backfill script, so they cannot drift apart:

1. find the number (``phone_identity.find_phones``: the phonenumbers matcher, so dates, prices, pincodes and reference numbers are
   not phones, and a number next to a date is still found);
2. attach it through ``identity_service.add_signal`` -- the ONLY place a phone signal is written. That makes the person a lead
   (``guests.lead_identified_at``), fills ``guests.phone``, and merges with a guest who already has that number;
3. move the enquiry from the "no phone yet" entry stage to the valid-lead entry stage (only from the default entry stage; a lead
   an agent already moved is left alone), through ``inquiry_service.update_stage_by_id`` so the transition hooks run;
4. close an open "Guest declined phone number" task on the conversation -- they have now shared it, and the inbox chip
   "No phone shared" must not stay up.

PII: the number is never logged; logs carry ``identity_service._phone_token``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.services import phone_identity

log = structlog.get_logger()

DECLINE_TASK_PREFIX = "Guest declined phone number"
_PHONE_TYPES = ("phone", "whatsapp_number")


def region_for(db: Session, tenant_id: str) -> str:
    """The country a number without a country code belongs to: the workspace's own, else India (what chat capture always used)."""
    from app.services.lead_auto_create import DEFAULT_REGION
    return phone_identity.region_for_tenant(db, tenant_id) or DEFAULT_REGION


def guest_has_phone(db: Session, tenant_id: str, guest_id: str) -> bool:
    """True when the guest already has a usable phone (a phone or WhatsApp-number signal)."""
    from app.models.guest_identity import GuestIdentity
    return db.query(GuestIdentity.id).filter(
        GuestIdentity.tenant_id == tenant_id, GuestIdentity.guest_id == guest_id,
        GuestIdentity.identity_type.in_(_PHONE_TYPES),
    ).first() is not None


def capture_from_text(
    db: Session, tenant_id: str, guest_id: str, text: Optional[str], *, source: str = "message_text",
    conversation=None, observed_at: Optional[datetime] = None, region: Optional[str] = None,
) -> Optional[str]:
    """Attach the first phone number in ``text`` to the guest. Returns the E.164 number, or None when the text holds none.

    Does not commit (the caller owns the transaction). Raises only what add_signal raises (an unknown guest)."""
    if not text or text.startswith("["):          # "[ig_post]", "[image]" ... are placeholders, not the guest's words
        return None
    found = phone_identity.find_phones(text, region or region_for(db, tenant_id))
    if not found:
        return None
    phone = found[0]
    from app.services import identity_service
    identity_service.add_signal(db, tenant_id, guest_id, "phone", phone, source=source, observed_at=observed_at)
    if conversation is not None:
        promote_inquiry(db, tenant_id, conversation)
        close_decline_tasks(db, tenant_id, conversation.id)
    log.info("chat_phone_captured", tenant_id=tenant_id, guest_id=guest_id, source=source,
             value_token=identity_service._phone_token(phone))
    return phone


def promote_inquiry(db: Session, tenant_id: str, conversation) -> bool:
    """Default-entry stage -> valid-lead entry stage, now that the guest gave a number. True when it moved.

    Real bug this preserves the fix for (moved here from process_instagram_dm): a phone shared after the opener left the enquiry in
    the default/invalid stage forever, so it never counted as a lead. ``actor_user_id=None`` (not "system"): it lands in
    audit_events.actor_user_id, a real foreign key to users."""
    if not getattr(conversation, "inquiry_id", None):
        return False
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage
    inquiry = db.query(Inquiry).filter_by(id=conversation.inquiry_id, tenant_id=tenant_id).first()
    if inquiry is None or not inquiry.stage_id:
        return False
    current = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=tenant_id).first()
    if current is None or not current.is_default_entry:
        return False
    valid_stage = db.query(PipelineStage).filter_by(tenant_id=tenant_id, is_valid_lead_entry=True).first()
    if valid_stage is None:
        return False
    from app.services import inquiry_service
    inquiry_service.update_stage_by_id(
        db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=valid_stage.id,
        actor_user_id=None, actor_role="system", reason="Guest shared phone number in conversation",
    )
    return True


def close_decline_tasks(db: Session, tenant_id: str, conversation_id: str) -> int:
    """Mark open "Guest declined phone number" tasks on this conversation done. Returns how many."""
    from app.models.task import Task
    tasks = db.query(Task).filter(
        Task.tenant_id == tenant_id, Task.conversation_id == conversation_id, Task.is_done.is_(False),
        Task.title.ilike(f"{DECLINE_TASK_PREFIX}%"),
    ).all()
    now = datetime.now(timezone.utc)
    for t in tasks:
        t.is_done = True
        t.completed_at = now
    return len(tasks)
