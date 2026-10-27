"""Ask a manager: open, answer, take over and read consults (the AI asking a person before it answers a guest).

  open_or_append   one OPEN consult per conversation; a later trigger on the same thread appends its reasons
  answer           a person answers: the text goes to the guest through the normal send path (24 h window open), else a
                   "Reply needed: window closed" task. Guarded UPDATE: two managers cannot both answer (409). Audited.
  take_over        a person replies themselves (guarded, audited); the AI holds its next drafts for 2 hours
  resolve_elsewhere  an open consult whose thread already got a human reply (Inbox approve / send) is closed as answered

Sending reuses the Inbox's own pieces: an approved AI draft (``was_approved``) or a human message, queued on send_whatsapp /
send_instagram_dm after commit, so it counts as human contact (work_queue_signals.touch_rows). Nothing here calls a model.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.agent_consult import AgentConsult
from app.models.conversation import Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.task import Task
from app.models.user import User
from app.services import agent_consult_settings as settings_svc
from app.services import agent_escalation_rules as rules

log = structlog.get_logger()

WINDOW = timedelta(hours=24)
TAKE_OVER_HOLD = timedelta(hours=2)


class ConsultError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _sha(text: Optional[str]) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _channel(conv: Conversation) -> str:
    return str(conv.channel.value if hasattr(conv.channel, "value") else conv.channel)


def open_consult(db: Session, tenant_id: str, conversation_id: str) -> Optional[AgentConsult]:
    return db.query(AgentConsult).filter_by(tenant_id=tenant_id, conversation_id=conversation_id, status="open").first()


def recently_taken_over(db: Session, tenant_id: str, conversation_id: str, now: Optional[datetime] = None) -> bool:
    since = (now or _now()) - TAKE_OVER_HOLD
    return db.query(AgentConsult.id).filter(
        AgentConsult.tenant_id == tenant_id, AgentConsult.conversation_id == conversation_id,
        AgentConsult.status == "taken_over", AgentConsult.answered_at >= since).first() is not None


def open_or_append(db: Session, tenant, conversation: Conversation, *, guest_id: Optional[str], inquiry, message_id: Optional[str],
                   question: str, proposed_answer: Optional[str], reasons: list[str], evidence: dict,
                   options: Optional[list] = None, now: Optional[datetime] = None) -> tuple[AgentConsult, bool]:
    """(consult, created). Flushes; the caller commits. A second open consult for the thread is never created: the partial
    unique index backs this up when two workers race (the loser appends instead)."""
    now = now or _now()
    existing = open_consult(db, tenant.id, conversation.id)
    if existing is not None:
        existing.reason_codes = list(dict.fromkeys(list(existing.reason_codes or []) + list(reasons)))
        existing.question = (existing.question + "\n" + question)[-2000:] if question and question not in existing.question else existing.question
        if proposed_answer:
            existing.proposed_answer = proposed_answer
        existing.message_id = message_id or existing.message_id
        existing.evidence = {**(existing.evidence or {}), **evidence}
        db.flush()
        return existing, False
    owner = conversation.assigned_to or getattr(inquiry, "assigned_to", None)
    consult = AgentConsult(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conversation.id, guest_id=guest_id,
        inquiry_id=getattr(inquiry, "id", None), message_id=message_id, channel=_channel(conversation),
        reason_codes=list(dict.fromkeys(reasons)), question=(question or "(no text)")[:2000], proposed_answer=proposed_answer,
        options=options, evidence=evidence, status="open", level="agent" if owner else "manager", assigned_to=owner,
        sla_due_at=settings_svc.sla_due(tenant, now), created_at=now, updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(consult)
    except Exception:                       # IntegrityError: another worker opened it a moment ago
        existing = open_consult(db, tenant.id, conversation.id)
        if existing is None:
            raise
        return open_or_append(db, tenant, conversation, guest_id=guest_id, inquiry=inquiry, message_id=message_id,
                              question=question, proposed_answer=proposed_answer, reasons=reasons, evidence=evidence, now=now)
    append_audit(db, tenant_id=tenant.id, action="agent_consult.opened", target_type="agent_consult", target_id=consult.id,
                 payload={"actor": "ai_concierge", "conversation_id": conversation.id, "reasons": consult.reason_codes})
    return consult, True


# ── reading ──────────────────────────────────────────────────────────────────

def _human_reply_after(db: Session, consult: AgentConsult) -> Optional[Message]:
    """A message a person sent or approved on this thread after the consult opened (answered in the Inbox instead)."""
    return (db.query(Message).filter(
        Message.tenant_id == consult.tenant_id, Message.conversation_id == consult.conversation_id,
        Message.direction == MessageDirection.OUTBOUND, Message.is_internal.isnot(True), Message.sent_autonomously.isnot(True),
        or_(Message.sender_kind.is_(None), Message.sender_kind.notin_(("playbook", "system", "campaign", "bridge_history",
                                                                         "ai_auto", "ai_holding"))),
        or_(Message.is_ai_generated.isnot(True), Message.was_approved.is_(True)),
        Message.created_at >= consult.created_at,
    ).order_by(Message.created_at.asc()).first())


def resolve_elsewhere(db: Session, consult: AgentConsult) -> bool:
    """Close an open consult whose guest already got a person's reply. Guarded; audited. Flushes."""
    if consult.status != "open":
        return False
    msg = _human_reply_after(db, consult)
    if msg is None:
        return False
    done = db.execute(update(AgentConsult).where(AgentConsult.id == consult.id, AgentConsult.status == "open").values(
        status="answered", answer_mode="inbox", answered_by=msg.sender_id, answered_at=_now(), answer_message_id=msg.id,
        delivery="queued", updated_at=_now()).execution_options(synchronize_session=False)).rowcount
    if done == 1:
        append_audit(db, tenant_id=consult.tenant_id, actor_user_id=msg.sender_id, action="agent_consult.answered",
                     target_type="agent_consult", target_id=consult.id, payload={"mode": "inbox", "message_id": msg.id})
        db.expire(consult)
    return done == 1


def view(db: Session, c: AgentConsult, names: Optional[dict] = None) -> dict:
    names = names or {}
    guest = db.query(Guest.name).filter_by(id=c.guest_id, tenant_id=c.tenant_id).first() if c.guest_id else None
    now = _now()
    due = _aware(c.sla_due_at)
    return {
        "id": c.id, "conversation_id": c.conversation_id, "guest_id": c.guest_id, "guest_name": (guest[0] if guest else None) or "Guest",
        "inquiry_id": c.inquiry_id, "message_id": c.message_id, "channel": c.channel, "status": c.status, "level": c.level,
        "reasons": rules.labels(c.reason_codes), "question": c.question, "proposed_answer": c.proposed_answer,
        "options": c.options or [], "evidence": c.evidence or {}, "assigned_to": c.assigned_to,
        "assigned_name": names.get(c.assigned_to), "sla_due_at": due.isoformat() if due else None,
        "overdue": bool(c.status == "open" and due and due < now), "created_at": _aware(c.created_at).isoformat(),
        "holding_sent": bool(c.holding_message_id), "answered_by": c.answered_by, "answered_name": names.get(c.answered_by),
        "answer_mode": c.answer_mode, "answer_text": c.answer_text,
        "answered_at": _aware(c.answered_at).isoformat() if c.answered_at else None, "delivery": c.delivery,
        "task_id": c.task_id, "saved_to_kb_entry_id": c.saved_to_kb_entry_id,
        "window_open": window_open(db, c.tenant_id, c.conversation_id) if c.status == "open" else None,
    }


def _names(db: Session, tenant_id: str, ids) -> dict:
    ids = [i for i in set(ids) if i]
    return dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()) if ids else {}


def list_consults(db: Session, tenant_id: str, *, status: Optional[str] = None, conversation_id: Optional[str] = None,
                  limit: int = 50) -> list[dict]:
    """Open first (oldest due first), then the most recently closed. Closes, on the way, consults answered in the Inbox."""
    q = db.query(AgentConsult).filter(AgentConsult.tenant_id == tenant_id)
    if conversation_id:
        q = q.filter(AgentConsult.conversation_id == conversation_id)
    rows = q.order_by(AgentConsult.created_at.desc()).limit(200).all()
    if any(resolve_elsewhere(db, r) for r in rows if r.status == "open"):
        db.commit()
        rows = q.order_by(AgentConsult.created_at.desc()).limit(200).all()
    if status:
        rows = [r for r in rows if r.status == status]
    opened = sorted([r for r in rows if r.status == "open"], key=lambda r: _aware(r.sla_due_at))
    closed = sorted([r for r in rows if r.status != "open"], key=lambda r: _aware(r.answered_at or r.created_at), reverse=True)
    rows = (opened + closed)[:limit]
    names = _names(db, tenant_id, [r.assigned_to for r in rows] + [r.answered_by for r in rows])
    return [view(db, r, names) for r in rows]


def get(db: Session, tenant_id: str, consult_id: str) -> AgentConsult:
    c = db.query(AgentConsult).filter_by(id=consult_id, tenant_id=tenant_id).first()
    if c is None:
        raise ConsultError(404, "not_found", "Consult not found")
    return c


# ── sending ──────────────────────────────────────────────────────────────────

def window_open(db: Session, tenant_id: str, conversation_id: str, now: Optional[datetime] = None) -> bool:
    """The guest wrote on THIS thread within 24 h (a personal-bridge mirror line never opens the business window)."""
    last = db.query(func.max(Message.created_at)).filter(
        Message.tenant_id == tenant_id, Message.conversation_id == conversation_id, Message.direction == MessageDirection.INBOUND,
    ).scalar()
    last = _aware(last)
    return bool(last and (now or _now()) - last <= WINDOW)


def queue_send(message_id: str, tenant_id: str, channel: str) -> None:
    """After commit: hand one message to the channel's sender task. Raises when the channel has no sender."""
    if channel == "instagram":
        from app.workers.tasks.send_instagram_dm import send_instagram_dm
        send_instagram_dm.delay(message_id=message_id, tenant_id=tenant_id)
    elif channel == "whatsapp":
        from app.workers.tasks.send_whatsapp import send_whatsapp
        send_whatsapp.delay(message_id=message_id, tenant_id=tenant_id)
    else:
        raise ConsultError(400, "channel_not_supported", f"Sending on the '{channel}' channel is not supported.")


def _final_text(c: AgentConsult, mode: str, text: Optional[str], option_id: Optional[str]) -> str:
    if mode == "approve_proposed":
        out = c.proposed_answer or ""
    elif mode == "edited":
        out = text or ""
    else:
        match = next((o for o in (c.options or []) if isinstance(o, dict) and str(o.get("id")) == str(option_id)), None)
        if match is None:
            raise ConsultError(422, "unknown_option", "That option is not on this consult.")
        out = str(match.get("text") or "")
    if not out.strip():
        raise ConsultError(422, "empty_answer", "There is no text to send.")
    return out.strip()


def _task(db: Session, c: AgentConsult, title: str, assigned_to: Optional[str], priority: str = "high") -> Task:
    t = Task(id=str(uuid.uuid4()), tenant_id=c.tenant_id, title=title[:255], priority=priority, guest_id=c.guest_id,
             inquiry_id=c.inquiry_id, conversation_id=c.conversation_id, assigned_to=assigned_to, due_date=_now(), kind="call")
    db.add(t)
    db.flush()
    return t


def _approve_draft(db: Session, c: AgentConsult, user: User, body: str) -> Optional[Message]:
    """Send the held AI draft itself (with the final text) when it is still pending: one guarded UPDATE, like the Inbox."""
    if not c.draft_message_id:
        return None
    draft = db.query(Message).filter_by(id=c.draft_message_id, tenant_id=c.tenant_id).first()
    if draft is None:
        return None
    seen = draft.body
    claimed = db.execute(update(Message).where(
        Message.id == draft.id, Message.tenant_id == c.tenant_id, Message.is_ai_generated.is_(True),
        Message.was_approved.is_(None), Message.channel_message_id.is_(None),
    ).values(was_approved=True, sender_id=user.id, delivery_state=MessageDeliveryState.QUEUED, body=body)
        .execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        return None
    db.refresh(draft)
    from app.services.ai_draft_outcomes_service import record_outcome
    edited = body != seen
    record_outcome(db, tenant_id=c.tenant_id, draft=draft, outcome="sent_edited" if edited else "sent_verbatim",
                   original_body=seen if edited else None, sent_body=body if edited else None, actor_user_id=user.id,
                   intent=draft.ai_intent)
    return draft


def _human_message(db: Session, c: AgentConsult, conv: Conversation, user: User, body: str) -> Message:
    msg = Message(id=str(uuid.uuid4()), tenant_id=c.tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=conv.channel, body=body, sender_id=user.id, sender_name=(user.name or "Team")[:255], sender_kind="human",
                  is_ai_generated=False, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued",
                  channel_metadata={"source": "agent_consult", "consult_id": c.id})
    db.add(msg)
    conv.last_message_at = _now().isoformat()
    db.flush()
    return msg


def _save_to_kb(db: Session, c: AgentConsult, user: User, answer: str) -> str:
    """A PENDING knowledge entry (unused until the owner approves it; the KB's own versioning and audit trail apply)."""
    from app.models.knowledge import KnowledgeEntry
    from app.services import knowledge_service
    entry = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=c.tenant_id, category="faq", question=(c.question or "")[:500],
                           content=answer, source="conversation", source_ref=f"consult:{c.id}", priority=0, is_active=True,
                           review_status="pending", embedding_status="pending", created_by=user.id)
    db.add(entry)
    db.flush()
    knowledge_service.audit_change(db, c.tenant_id, user.id, "created", entry.id, after=knowledge_service.snapshot(entry),
                                   source="agent_consult", consult_id=c.id)
    return entry.id


def answer(db: Session, user: User, consult_id: str, mode: str, text: Optional[str] = None, option_id: Optional[str] = None,
           save_to_kb: bool = False) -> dict:
    """Answer a consult. Commits, then queues the send. Raises ConsultError (404 / 409 / 422)."""
    c = get(db, user.tenant_id, consult_id)
    if c.status != "open":
        raise ConsultError(409, f"consult_{c.status}", "Someone already dealt with this question.")
    body = _final_text(c, mode, text, option_id)
    now = _now()
    claimed = db.execute(update(AgentConsult).where(AgentConsult.id == c.id, AgentConsult.tenant_id == user.tenant_id,
                                                    AgentConsult.status == "open").values(
        status="answered", answered_by=user.id, answered_at=now, answer_mode=mode, answer_text=body, updated_at=now,
    ).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        raise ConsultError(409, "consult_already_answered", "Someone already dealt with this question.")
    db.refresh(c)
    conv = db.query(Conversation).filter_by(id=c.conversation_id, tenant_id=user.tenant_id).first()
    channel = _channel(conv) if conv else None
    to_send: Optional[Message] = None
    if conv is None or conv.is_personal_bridge or channel not in ("whatsapp", "instagram") \
            or not window_open(db, user.tenant_id, conv.id, now):
        who = (db.query(Guest.name).filter_by(id=c.guest_id, tenant_id=c.tenant_id).scalar() if c.guest_id else None) or "guest"
        t = _task(db, c, f"Reply needed: window closed — {who} (answer saved on the consult)", user.id)
        c.task_id, c.delivery = t.id, "window_closed_task"
    else:
        to_send = _approve_draft(db, c, user, body) or _human_message(db, c, conv, user, body)
        c.answer_message_id, c.delivery = to_send.id, "queued"
    if save_to_kb:
        c.saved_to_kb_entry_id = _save_to_kb(db, c, user, body)
    append_audit(db, tenant_id=c.tenant_id, actor_user_id=user.id, action="agent_consult.answered", target_type="agent_consult",
                 target_id=c.id, payload={"mode": mode, "delivery": c.delivery, "body_sha256": _sha(body),
                                          "saved_to_kb": bool(save_to_kb), "message_id": c.answer_message_id})
    if conv is not None and to_send is not None:
        from app.services import lead_reopen
        lead_reopen.on_contact(db, c.tenant_id, conv.guest_id, trigger="team_message", by_guest=False, actor_user_id=user.id)
    if conv is not None:
        from app.services.lead_assignment_service import claim_on_first_touch
        claim_on_first_touch(db, c.tenant_id, conv.guest_id, user.id)
    db.commit()
    if to_send is not None:
        try:
            queue_send(to_send.id, c.tenant_id, channel)
        except Exception as exc:      # the broker is down: say so on the message instead of leaving it "queued" forever
            log.error("consult_answer_enqueue_failed", consult_id=c.id, error=str(exc)[:200])
            to_send.delivery_state = MessageDeliveryState.FAILED
            to_send.delivery_error = "Could not queue the message for sending. Retry it from the Inbox."
            c.delivery = "not_sent"
            db.commit()
    return {"status": c.status, "delivery": c.delivery, "message_id": c.answer_message_id, "task_id": c.task_id,
            "kb_entry_id": c.saved_to_kb_entry_id}


def take_over(db: Session, user: User, consult_id: str) -> dict:
    c = get(db, user.tenant_id, consult_id)
    now = _now()
    claimed = db.execute(update(AgentConsult).where(AgentConsult.id == c.id, AgentConsult.tenant_id == user.tenant_id,
                                                    AgentConsult.status == "open").values(
        status="taken_over", answered_by=user.id, answered_at=now, answer_mode="take_over", updated_at=now,
    ).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        db.refresh(c)
        raise ConsultError(409, f"consult_{c.status}", "Someone already dealt with this question.")
    conv = db.query(Conversation).filter_by(id=c.conversation_id, tenant_id=user.tenant_id).first()
    if conv is not None and not conv.assigned_to:
        conv.assigned_to = user.id
    append_audit(db, tenant_id=c.tenant_id, actor_user_id=user.id, action="agent_consult.taken_over", target_type="agent_consult",
                 target_id=c.id, payload={"conversation_id": c.conversation_id})
    db.commit()
    return {"status": "taken_over", "conversation_id": c.conversation_id}

