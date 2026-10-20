"""AI-drafted follow-up for a lead (playbooks P5 / P6 in "drafts" mode): a short WhatsApp message a PERSON approves and
sends from the inbox. Never sent by itself.

Runs only in Celery (``lead_playbooks.draft_followup``), through the LLM router (task "lead_followup_draft"), never
inline in a request. The model sees the last messages of the guest's official WhatsApp thread (prices stripped), the trip
facts on the lead and what this follow-up is for. Guards on the reply:
  * no price, ever (price_policy.detect_price): follow-ups chase, they do not quote; pricing goes through the rate
    calculator. A reply with a price, an empty reply, or a provider failure falls back to the playbook's fixed wording.
  * at most 600 characters.
The draft is stored like a concierge draft (is_ai_generated, was_approved NULL), so it shows in the inbox with Approve /
Edit / Reject and the existing approve endpoint sends it; it counts as contact only once a person approves it.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.prompt_versions import PROMPT_VERSIONS
from app.models.conversation import Conversation, Message, MessageDirection

log = structlog.get_logger()

PROMPT_KEY = "lead_followup_draft"
TIMEOUT_S = 45
MAX_CHARS = 600

PURPOSE = {
    "nudge": "We shared a proposal a few hours ago and the guest has not replied. Check they received it and offer to "
             "answer questions or adjust it.",
    "final": "The proposal is still unanswered after a week. A friendly last call: ask whether to hold the dates.",
    "day1": "We wrote last and the guest has been quiet for a day. A light, helpful follow-up that invites a reply.",
    "checkin": "The guest has been quiet for three days. Ask whether they are still planning the trip and invite their "
               "dates.",
}

SYSTEM_PROMPT = (
    "You write ONE short WhatsApp follow-up message (1 to 3 sentences, under 60 words) from a hospitality business to a "
    "guest who enquired about a trip. Warm, natural, Indian English, no emojis unless the guest used them. Use the guest's "
    "first name if known. Refer to their trip using only the facts given. Never mention any price, amount, discount or "
    "number of rupees, and never invent dates, availability or offers. No greetings like 'Dear customer'. Output only the "
    "message text."
)


def _facts(db: Session, inquiry, guest) -> str:
    bits = []
    if guest is not None and guest.name and guest.name.lower() not in ("unknown", "guest"):
        bits.append(f"Guest first name: {guest.name.split(' ')[0]}")
    if inquiry is not None:
        if inquiry.route_mentioned:
            bits.append(f"Trip / route: {inquiry.route_mentioned}")
        if inquiry.check_in:
            bits.append(f"Check-in: {inquiry.check_in}")
        if inquiry.adults:
            bits.append(f"Guests: {inquiry.adults} adults" + (f", {inquiry.children} children" if inquiry.children else ""))
    return "\n".join(bits) or "No trip details on file."


def _thread(db: Session, conversation_id: str, limit: int = 12) -> str:
    from app.services.price_policy import strip_prices
    rows = (db.query(Message).filter(Message.conversation_id == conversation_id, Message.is_internal.isnot(True),
                                     Message.body.isnot(None))
            .order_by(Message.created_at.desc()).limit(limit).all())
    lines = []
    for m in reversed(rows):
        who = "Guest" if m.direction == MessageDirection.INBOUND else "Us"
        lines.append(f"{who}: {strip_prices((m.body or '')[:400])}")
    return "\n".join(lines) or "(no messages yet)"


async def _complete(user_message: str) -> str:
    from app.adapters.llm import get_llm
    llm = get_llm(PROMPT_KEY)
    resp = await asyncio.wait_for(llm.complete(system_prompt=SYSTEM_PROMPT, user_message=user_message, max_tokens=300),
                                  timeout=TIMEOUT_S)
    return (resp.get("content") or "").strip()


def check_reply(reply: str) -> Optional[str]:
    """None when the draft may be shown, else why it is replaced by the fixed wording."""
    from app.services.price_policy import detect_price
    if not reply:
        return "empty reply"
    if len(reply) > MAX_CHARS:
        return "too long"
    if detect_price(reply):
        return "mentions a price"
    return None


def write_draft(db: Session, tenant_id: str, conversation_id: str, inquiry, guest, purpose: str, fallback_text: str,
                run_id: str) -> Optional[str]:
    """Store one pending AI draft in the conversation. Returns the message id. The caller commits."""
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first()
    if conv is None:
        return None
    version = PROMPT_VERSIONS.get(PROMPT_KEY, "unregistered")
    user_message = (f"What this follow-up is for: {PURPOSE.get(purpose, PURPOSE['day1'])}\n\n"
                    f"Facts:\n{_facts(db, inquiry, guest)}\n\nRecent conversation (oldest first):\n{_thread(db, conversation_id)}")
    source = "ai"
    try:
        reply = asyncio.run(_complete(user_message))
        reason = check_reply(reply)
    except Exception as exc:  # noqa: BLE001 -- provider error or timeout: the fixed wording is still a useful draft
        reply, reason = "", f"provider {type(exc).__name__}"
    if reason:
        log.warning("followup_draft_fallback", tenant_id=tenant_id, conversation_id=conversation_id, reason=reason,
                    prompt_version=version)
        reply, source = fallback_text, "fixed"
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=conv.channel, body=reply[:MAX_CHARS], is_ai_generated=True, was_approved=None,
                  sender_name="AI follow-up",
                  channel_metadata={"source": "playbook", "run_id": run_id, "purpose": purpose, "draft_source": source,
                                    "prompt_version": version})
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    log.info("followup_draft_stored", tenant_id=tenant_id, message_id=msg.id, source=source, prompt_version=version)
    return msg.id
