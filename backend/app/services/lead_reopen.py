"""Bring a lead back when the GUEST is in touch again (owner, 28 Oct 2026; tightened 1 Nov 2026).

The rule, ONE place for it:
  - a Lost lead reopens (to ``StageMap.qualified``, Active) only when the GUEST responds: they write (WhatsApp, Instagram,
    a live message to the team's personal WhatsApp), they call us, or they pick up our call. Our own outreach (a message,
    an unanswered call) leaves it Lost, whether a PERSON or the SYSTEM closed it (S1/S2);
  - a reply to a WhatsApp campaign (``on_campaign_reply``, any days later) moves the guest's newest enquiry to Active from
    Lost (on_contact, just before) and from a "not engaged yet" stage (General Enquiry, Unqualified, RNR: quote_calc_service._not_engaged); never
    from Sold or a stage a person chose (S3);
  - Sold is never reopened; only the guest's NEWEST enquiry is reopened, and only while no other enquiry of theirs is open
    (no duplicate lead).
Either way the enquiry is stamped ``returned_at`` / ``returned_via`` (came_back | campaign_reply), and the work queue lists
it under that kind from the return time until a person contacts the guest (work_queue_returns).

Live events only: history imports, backfills and uploaded evidence never call this. Every reopen goes through
``inquiry_service.reopen_lost_inquiry`` (stage log, ledger event, ``inquiry.stage_changed`` audit, lost reason cleared) and
writes a ``lead.auto_reopened`` audit row naming the trigger. Best-effort: a failure is logged, never breaks the ingest.
Callers: whatsapp.py (+ on_campaign_reply) / process_instagram_dm.py / whatsapp_personal_service.py (the guest's live
messages), call_ingest.py + lead_call_log.py (calls). Caller commits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry, InquiryStage
from app.models.pipeline_stage import PipelineStage

log = structlog.get_logger()

_CLOSED_LEGACY = (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)

#: trigger -> the words in the stage log / audit
TRIGGERS = {
    "whatsapp_message": "the guest wrote on WhatsApp",
    "instagram_message": "the guest wrote on Instagram",
    "personal_whatsapp_message": "the guest wrote to the team's WhatsApp",
    "inbound_call": "the guest called",
    "outbound_call_connected": "the guest picked up our call",
    "campaign_reply": "the guest replied to a WhatsApp campaign",
}


def lost_lead(db: Session, tenant_id: str, guest_id: Optional[str]) -> tuple[Optional[Inquiry], Optional[PipelineStage]]:
    """The guest's newest enquiry and its stage, when that enquiry sits in a Lost stage and no enquiry of theirs is open."""
    if not guest_id:
        return None, None
    # Judged by the pipeline stage, not the legacy enum (older Lost rows can still carry an open enum value).
    rows = (db.query(Inquiry, PipelineStage)
            .outerjoin(PipelineStage, (PipelineStage.id == Inquiry.stage_id) & (PipelineStage.tenant_id == tenant_id))
            .filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id)
            .order_by(Inquiry.created_at.desc()).all())
    if not rows:
        return None, None
    if any(st is None and i.stage not in _CLOSED_LEGACY or st is not None and not (st.is_closed_won or st.is_closed_lost)
           for i, st in rows):
        return None, None                               # an open enquiry takes the activity
    inquiry, stage = rows[0]
    return (inquiry, stage) if stage is not None and stage.is_closed_lost else (None, None)


def closed_by_system(db: Session, inquiry: Inquiry, stage: PipelineStage) -> bool:
    """True when the latest move into this Lost stage was automatic. No log = we can't tell = a person."""
    from app.models.inquiry_360 import InquiryStageLog
    last = (db.query(InquiryStageLog).filter_by(tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, to_stage=stage.key)
            .order_by(InquiryStageLog.changed_at.desc()).first())
    return last is not None and last.changed_by == "system"


def mark_returned(inquiry: Inquiry, via: str, campaign_id: Optional[str] = None) -> None:
    """Stamp the return, so the work queue lists the lead from now (not from its first arrival)."""
    inquiry.returned_at, inquiry.returned_via, inquiry.returned_campaign_id = datetime.now(timezone.utc), via, campaign_id


def reopen(db: Session, inquiry: Inquiry, stage: PipelineStage, *, trigger: str, by_guest: bool,
           actor_user_id: Optional[str] = None, via: str = "came_back", campaign_id: Optional[str] = None) -> bool:
    """Apply the rule to one Lost lead. True when it was reopened."""
    from app.core.audit import append_audit
    from app.services import inquiry_service
    from app.services.lead_autopilot_rules import StageMap

    if stage is None or not stage.is_closed_lost or not by_guest:
        return False                                    # only the guest responding brings a Lost lead back (S2)
    target = StageMap.load(db, inquiry.tenant_id).qualified
    if target is None:
        return False
    system = closed_by_system(db, inquiry, stage)
    words = TRIGGERS.get(trigger, trigger)
    inquiry_service.reopen_lost_inquiry(
        db, tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, new_stage_id=target.id, actor_user_id=actor_user_id,
        actor_role="system", reason=f"Reopened automatically: {words}")
    mark_returned(inquiry, via, campaign_id)
    append_audit(db, tenant_id=inquiry.tenant_id, action="lead.auto_reopened", actor_user_id=actor_user_id,
                 target_type="inquiry", target_id=inquiry.id,
                 payload={"trigger": trigger, "closed_by": "system" if system else "person", "from_stage": stage.key,
                          "to_stage": target.key, **({"campaign_id": campaign_id} if campaign_id else {}),
                          **({} if actor_user_id else {"actor": "system"})})
    log.info("lead_auto_reopened", tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, trigger=trigger,
             closed_by="system" if system else "person")
    return True


def on_call(db: Session, call) -> Optional[Inquiry]:
    """A call was just recorded (IVR ingest, a logged call). The guest calling us is the guest in touch (answered or
    missed); our call counts only once the guest picked up (lead_task_closer.connected: a conclusive signal, never
    duration). An unanswered call of ours leaves the lead Lost."""
    from app.services.lead_task_closer import connected
    inbound = str(getattr(call.direction, "value", call.direction)).lower() == "inbound"
    if not inbound and not connected(call):
        return None
    return on_contact(db, call.tenant_id, call.guest_id, trigger="inbound_call" if inbound else "outbound_call_connected",
                      by_guest=True, actor_user_id=None if inbound else call.agent_id)


def on_contact(db: Session, tenant_id: str, guest_id: Optional[str], *, trigger: str, by_guest: bool,
               actor_user_id: Optional[str] = None) -> Optional[Inquiry]:
    """A live contact with this guest: reopen their Lost lead if the rule says so. Returns the reopened lead, else None."""
    try:
        with db.begin_nested():
            inquiry, stage = lost_lead(db, tenant_id, guest_id)
            if inquiry is None:
                return None
            return inquiry if reopen(db, inquiry, stage, trigger=trigger, by_guest=by_guest, actor_user_id=actor_user_id) else None
    except Exception as exc:  # noqa: BLE001 -- best-effort: the message / call itself must still be stored
        log.warning("lead_auto_reopen_failed", tenant_id=tenant_id, trigger=trigger, error=str(exc)[:200])
        return None


# ── S3: a reply to a WhatsApp campaign ──────────────────────────────────────────────────────────────────────────────

def campaign_replied_to(db: Session, tenant_id: str, guest_id: str, message) -> Optional[tuple[str, Optional[str]]]:
    """(campaign_id, campaign name) when this inbound WhatsApp message is the guest's first since a campaign reached them,
    else None. The campaign report's "Replied" matching (wa_campaign_delivery.replies: recipient phone = guest phone, an
    inbound WhatsApp after the send) without its 7-day window: the owner counts a reply any days later."""
    from sqlalchemy import func

    from app.api.v1.endpoints.messaging import WACampaign
    from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
    from app.models.guest import Guest
    from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if guest is None or not guest.phone or message is None or message.created_at is None:
        return None
    sent = (db.query(Recipient.campaign_id, Recipient.sent_at)
            .filter(Recipient.tenant_id == tenant_id, Recipient.phone == guest.phone, Recipient.sent_at.isnot(None),
                    Recipient.sent_at <= message.created_at)
            .order_by(Recipient.sent_at.desc()).first())
    if sent is None:
        return None
    earlier = (db.query(func.count(Message.id)).join(Conversation, Conversation.id == Message.conversation_id)
               .filter(Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                       Conversation.channel == ChannelType.WHATSAPP, Message.direction == MessageDirection.INBOUND,
                       Message.id != message.id, Message.created_at >= sent.sent_at,
                       Message.created_at <= message.created_at).scalar())
    if earlier:
        return None                                     # they already answered this campaign
    campaign = db.query(WACampaign).filter_by(id=sent.campaign_id, tenant_id=tenant_id).first()
    return sent.campaign_id, getattr(campaign, "name", None)


def on_campaign_reply(db: Session, tenant_id: str, guest_id: Optional[str], message) -> Optional[Inquiry]:
    """S3: this WhatsApp is the guest's reply to a campaign -> their newest enquiry goes to Active from a "not engaged yet"
    stage and is stamped campaign_reply with the campaign; a stage a person chose keeps its stage (stamp only); Sold or Lost:
    nothing. Call it AFTER on_contact (which already reopened a Lost lead) and after the chat's lead was created, so a
    subscriber's first enquiry is stamped too. Best-effort, savepoint. Returns the enquiry it stamped, else None."""
    from app.core.audit import append_audit
    from app.services import inquiry_service
    from app.services.lead_autopilot_rules import StageMap
    from app.services.quote_calc_service import _not_engaged

    if not guest_id:
        return None
    try:
        with db.begin_nested():
            hit = campaign_replied_to(db, tenant_id, guest_id, message)
            if hit is None:
                return None
            campaign_id, name = hit
            inquiry = (db.query(Inquiry).filter_by(tenant_id=tenant_id, guest_id=guest_id)
                       .order_by(Inquiry.created_at.desc()).first())
            stages = StageMap.load(db, tenant_id)
            current = stages.by_id(inquiry.stage_id) if inquiry is not None else None
            if current is None or current.is_closed_won or current.is_closed_lost:
                return None
            target = stages.qualified
            moved = target is not None and target.id != current.id and _not_engaged(current)
            if moved:
                inquiry_service.update_stage_by_id(
                    db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=target.id, actor_user_id=None,
                    actor_role="system", reason=f"Replied to the WhatsApp campaign {name or ''}".strip())
            mark_returned(inquiry, "campaign_reply", campaign_id)
            append_audit(db, tenant_id=tenant_id, action="lead.campaign_reply", target_type="inquiry", target_id=inquiry.id,
                         payload={"campaign_id": campaign_id, "campaign": name, "from_stage": current.key,
                                  "to_stage": target.key if moved else current.key, "actor": "system"})
            return inquiry
    except Exception as exc:  # noqa: BLE001 -- best-effort: the message itself must still be stored
        log.warning("lead_campaign_reply_failed", tenant_id=tenant_id, error=str(exc)[:200])
        return None
