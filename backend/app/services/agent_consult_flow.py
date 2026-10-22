"""The concierge's "Ask a manager" step: two hooks in workers/tasks/concierge_draft.py.

  check_turn   after every guard ran and BEFORE the draft is stored or sent: gather the inputs, run the deterministic rules
               (agent_escalation_rules). A fired trigger means the guessed answer is NOT sent (it stays a pending draft and
               becomes the consult's proposed answer).
  after_draft  once the draft is stored: open (or append to) the conversation's ONE open consult, send ONE honest holding reply
               where allowed, and tell the team (agent_consult_notify).

Consults open only where the AI would otherwise answer on its own (the channel's AI mode is autonomous): in draft/shadow mode
staff already review every reply. A forced "write a draft" click, a superseded run and a personal-bridge thread never open one.
The holding reply goes only on WhatsApp / Instagram, inside the 24 h window, never into a personal-bridge thread, never twice in
a row (Intercom rule), and not while the AI's send rate limit is hit.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.agent_consult import AgentConsult
from app.models.conversation import Conversation, Message, MessageDeliveryState, MessageDirection
from app.services import agent_consult_service as svc
from app.services import agent_consult_settings as settings_svc
from app.services import agent_escalation_rules as rules

log = structlog.get_logger()

HISTORY_WINDOW = timedelta(hours=24)
HOLDING_KIND = "ai_holding"


@dataclass
class ConsultTurn:
    reasons: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    hold: bool = False                  # do not auto-send the draft
    note: Optional[str] = None          # appended to the draft's needs-human reason
    question: str = ""
    message_id: Optional[str] = None
    rate_limited: bool = False
    consult_id: Optional[str] = None

    @property
    def owns_price(self) -> bool:
        """The consult replaces the old "Call lead about pricing" task when it opened for a price question."""
        return "price_handoff" in self.reasons


def _channel(conv: Conversation) -> str:
    return str(conv.channel.value if hasattr(conv.channel, "value") else conv.channel)


def history(db: Session, tenant_id: str, conversation_id: str, now: Optional[datetime] = None) -> list[dict]:
    """The last 24 h of the thread, oldest first, as the plain dicts the rules read. ``human`` = a person sent or approved it."""
    since = (now or datetime.now(timezone.utc)) - HISTORY_WINDOW
    rows = (db.query(Message).filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                                     Message.is_internal.isnot(True), Message.created_at >= since)
            .order_by(Message.created_at.asc()).limit(80).all())
    out = []
    for m in rows:
        d = str(getattr(m.direction, "value", m.direction)).lower()
        ai = bool(m.is_ai_generated)
        human = d == "outbound" and not m.sent_autonomously and m.sender_kind not in (
            "playbook", "system", "campaign", "bridge_history", "ai_auto", HOLDING_KIND) and (not ai or m.was_approved is True)
        out.append({"direction": d, "body": m.body or "", "ai": ai, "intent": m.ai_intent, "human": human,
                    "sent": bool(m.sent_autonomously or m.was_approved is True), "holding": m.sender_kind == HOLDING_KIND})
    return out


def check_turn(db: Session, tenant, conversation: Conversation, guest, inquiry, *, message_id: str, ai_mode: str, force: bool,
               burst_text: str, intent: str, details: dict, grounded_facts: list, reply_text: str, model_confidence: float,
               threshold: float, escalation: Optional[dict], price_mode: str, price_leak, ungrounded: Optional[str],
               model_failed: bool, sales_turn=None, rate_limited: bool = False) -> ConsultTurn:
    """Evaluate the triggers for this turn. Never raises: a failure here leaves the turn as it was (logged)."""
    turn = ConsultTurn(message_id=message_id, rate_limited=rate_limited, question=(burst_text or "").strip()[:2000])
    try:
        if force or ai_mode != "autonomous" or conversation.is_personal_bridge or not settings_svc.get(tenant)["enabled"]:
            return turn
        from app.services.concierge_service import is_latest_pending_draft
        if not is_latest_pending_draft(tenant.id, conversation.id, message_id):
            return turn                                              # a newer run answers this message too
        if svc.recently_taken_over(db, tenant.id, conversation.id):
            turn.hold, turn.note = True, "a person took this conversation over: the AI only drafts"
            return turn
        from app.services.sales_agent_service import OWN_WORK_STATUSES
        sales_owns = bool(sales_turn is not None and (getattr(sales_turn, "action_id", None)
                                                      or getattr(sales_turn, "status", None) in OWN_WORK_STATUSES))
        signals = rules.TurnSignals(
            burst_text=burst_text or "", intent=intent or "general", details=details or {}, grounded_facts=grounded_facts or [],
            reply_text=reply_text or "", confidence=float(model_confidence or 0), threshold=float(threshold or 0),
            escalation=escalation, price_mode=price_mode, price_leak=price_leak, ungrounded=ungrounded, model_failed=model_failed,
            has_phone=getattr(guest, "lead_identified_at", None) is not None, sales_owns_price=sales_owns,
            sales_handoff=getattr(sales_turn, "handoff", None) if sales_turn is not None else None,
            history=history(db, tenant.id, conversation.id),
        )
        verdict = rules.evaluate(signals)
        # Who may decide what (agent_policy): the owner's mode per action class keeps, drops or adds a reason.
        from app.services import agent_policy
        reasons, policy_hold, notes = agent_policy.apply(tenant, intent, reply_text, verdict.reasons)
        if notes:
            verdict.evidence["policy"] = notes
        if reasons:
            turn.reasons, turn.evidence, turn.hold = reasons, verdict.evidence, True
            turn.note = "asked a manager: " + ", ".join(reasons)
        elif policy_hold:
            turn.hold, turn.note = True, "; ".join(notes)
    except Exception as exc:  # noqa: BLE001 -- the guards above still decide; the consult is an addition
        log.warning("consult_check_failed", conversation_id=conversation.id, error=str(exc)[:300])
    return turn


def _last_outbound(db: Session, tenant_id: str, conversation_id: str) -> Optional[Message]:
    return (db.query(Message).filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                                     Message.direction == MessageDirection.OUTBOUND, Message.is_internal.isnot(True),
                                     # a held (unsent) AI draft is not something the guest saw
                                     ~((Message.is_ai_generated.is_(True)) & (Message.was_approved.is_(None))))
            .order_by(Message.created_at.desc()).first())


def _holding_allowed(db: Session, tenant, conversation: Conversation, turn: ConsultTurn) -> Optional[str]:
    """None when the holding reply may go, else why not (stored in the consult's evidence)."""
    if not settings_svc.get(tenant)["send_holding_reply"]:
        return "switched off"
    if conversation.is_personal_bridge:
        return "personal WhatsApp thread"
    if _channel(conversation) not in ("whatsapp", "instagram"):
        return "channel cannot send"
    if turn.rate_limited:
        return "AI send rate limit"
    if not svc.window_open(db, tenant.id, conversation.id):
        return "24-hour window closed"
    last = _last_outbound(db, tenant.id, conversation.id)
    if last is not None and last.sender_kind == HOLDING_KIND:
        return "already sent a holding reply"
    return None


def _send_holding(db: Session, tenant, conversation: Conversation, consult: AgentConsult) -> Optional[Message]:
    text = settings_svc.holding_text(tenant)
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conversation.id, direction=MessageDirection.OUTBOUND,
                  channel=conversation.channel, body=text, is_ai_generated=False, sent_autonomously=True,
                  sender_kind=HOLDING_KIND, sender_name="AI Concierge", was_approved=True,
                  delivery_state=MessageDeliveryState.QUEUED, channel_status="queued",
                  idempotency_key=f"consult-hold:{consult.id}:{consult.message_id or ''}"[:64],
                  channel_metadata={"source": "agent_consult", "consult_id": consult.id, "holding": True})
    db.add(msg)
    conversation.last_message_at = datetime.now(timezone.utc).isoformat()
    consult.holding_message_id = msg.id
    return msg


def after_draft(db: Session, turn: ConsultTurn, draft: Optional[Message], tenant, conversation: Conversation, guest,
                inquiry) -> Optional[str]:
    """Open/append the consult, send the holding reply, notify. Returns the consult id. Never raises (a failure is logged and the
    held draft is still in the Inbox, as before)."""
    if not turn.reasons:
        return None
    try:
        consult, created = svc.open_or_append(
            db, tenant, conversation, guest_id=getattr(guest, "id", None) or conversation.guest_id, inquiry=inquiry,
            message_id=turn.message_id, question=turn.question, proposed_answer=(draft.body if draft is not None else None),
            reasons=turn.reasons, evidence=turn.evidence)
        if draft is not None:
            consult.draft_message_id = draft.id
        blocked = _holding_allowed(db, tenant, conversation, turn)
        holding = _send_holding(db, tenant, conversation, consult) if blocked is None else None
        if blocked:
            consult.evidence = {**(consult.evidence or {}), "holding_not_sent": blocked}
        if created:
            from app.services import agent_consult_notify as notify
            notify.notify(db, tenant, consult)
        db.commit()
        turn.consult_id = consult.id
        if holding is not None:
            try:
                svc.queue_send(holding.id, tenant.id, _channel(conversation))
            except Exception as exc:  # noqa: BLE001
                log.error("consult_holding_enqueue_failed", consult_id=consult.id, error=str(exc)[:200])
        log.info("consult_opened" if created else "consult_appended", tenant_id=tenant.id, consult_id=consult.id,
                 reasons=turn.reasons, holding_sent=holding is not None, holding_blocked=blocked)
        return consult.id
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error("consult_open_failed", conversation_id=conversation.id, error=str(exc)[:300])
        return None
