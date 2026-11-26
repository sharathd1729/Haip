"""The WhatsApp hours-and-welcome replies (settings: services/wa_bot_settings.py), called once per inbound guest message
from workers/tasks/whatsapp.py.

ONE automatic reply per inbound message. Order (the first that applies wins, the rest stay out):
  1. STOP / START       opt_out_responder (earlier in the inbound task): the confirmation, then nothing else on a STOP.
  2. Location reply     a shared location pin gets the owner's text (+ map link). The AI and keyword replies stay out.
  3. Welcome            the first message a brand-new contact ever sends (no earlier WhatsApp message with them, either
                        way): the owner's text + up to 3 reply buttons, at most once per contact (idempotency key
                        "wb:{guest_id}:welcome", unique per tenant). Keyword replies stay out. The AI concierge still
                        answers after it when ``also_when_ai_replies`` (default); otherwise the welcome goes only when the AI
                        is not going to answer by itself (mode off/shadow).
  4. Keyword replies    wa_keyword_replies (incl. the away message on hours "closed").
  5. AI concierge.

Location replies and welcomes are sent with sender_kind ``automation_away``: like the away message they never count as
an answer or a person's contact, so the guest stays on Needs reply / My day for the team.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.services import wa_bot_settings
from app.services.wa_keyword_replies import AWAY_KIND

log = structlog.get_logger()


def _first_name(guest) -> str:
    name = (getattr(guest, "name", "") or "").strip()
    return name.split()[0] if name and name.lower() != "unknown" else "there"


def is_first_contact(db: Session, tenant_id: str, guest_id: str, message_id: str) -> bool:
    """No other message, in or out, on any of this guest's WhatsApp conversations."""
    other = (db.query(Message.id).join(Conversation, Conversation.id == Message.conversation_id)
             .filter(Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                     Conversation.channel == ChannelType.WHATSAPP, Message.tenant_id == tenant_id, Message.id != message_id)
             .first())
    return other is None


def _ai_will_answer(tenant, conversation, message) -> bool:
    from app.services.ai_mode_service import can_send, resolve_mode
    return can_send(conversation, message) and resolve_mode(tenant, conversation, message) == "autonomous"


def _queue(db: Session, tenant_id: str, guest, conversation, text: str, *, name: str, source: str,
           idem: Optional[str] = None, buttons: Optional[list] = None) -> bool:
    """Store one automatic reply and queue it. False when the idempotency key was already used (sent before)."""
    meta = {"source": source, **({"interactive": {"kind": "buttons", "buttons": buttons}} if buttons else {})}
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation.id,
                  direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                  body=text.replace("{first_name}", _first_name(guest))[:1024], sender_kind=AWAY_KIND, sender_name=name,
                  channel_metadata=meta, delivery_state=MessageDeliveryState.PENDING, idempotency_key=idem)
    if idem and db.query(Message.id).filter_by(tenant_id=tenant_id, idempotency_key=idem).first():
        return False
    try:
        with db.begin_nested():
            db.add(msg)
            db.flush()
    except IntegrityError:                          # a concurrent delivery already took the key
        return False
    db.commit()
    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=msg.id, tenant_id=tenant_id)
    return True


def on_inbound(db: Session, tenant, guest, conversation, message, msg_type: str) -> Optional[str]:
    """"location" (replied: nothing else answers this message), "welcome" (sent: keyword replies stay out, the AI follows
    its own rules) or None. Never raises: a failure here must not lose the normal reply path."""
    try:
        s = wa_bot_settings.get(tenant)
        loc = s["location_reply"]
        if msg_type == "location" and loc["enabled"]:
            text = loc["text"] + (f"\n{loc['map_link']}" if loc["map_link"] else "")
            if _queue(db, tenant.id, guest, conversation, text, name="Location reply", source="location_reply",
                      idem=f"lr:{message.id}"[:64]):
                message.automation_outcome = "location_auto_replied"
                db.commit()
                log.info("wa_location_reply_sent", tenant_id=tenant.id, conversation_id=conversation.id)
                return "location"
        w = s["welcome"]
        if (w["enabled"] and is_first_contact(db, tenant.id, guest.id, message.id)
                and (w["also_when_ai_replies"] or not _ai_will_answer(tenant, conversation, message))):
            if _queue(db, tenant.id, guest, conversation, w["text"], name="Welcome message", source="welcome",
                      idem=f"wb:{guest.id}:welcome", buttons=w["buttons"] or None):
                log.info("wa_welcome_sent", tenant_id=tenant.id, conversation_id=conversation.id)
                return "welcome"
    except Exception as exc:  # noqa: BLE001 -- fall through to keyword replies / the AI
        db.rollback()
        log.warning("wa_bot_reply_failed", tenant_id=getattr(tenant, "id", None), error=str(exc)[:200])
    return None
