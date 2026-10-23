"""A guest asking for a collaboration / barter / influencer deal: a PERSON answers yes or no (Rathaa, Oct 2026).

Live bug: weeks after "Hey!" a guest asked "Can you give barter collaboration". The AI promised "the team will reach out" four
times in four weeks, nobody did, no task existed and the lead ended Lost instead of in the tenant's collaboration stage. The
first-message routing (lead_auto_create) never saw it: the request came mid-conversation.

  pending()            the guest's oldest collaboration request in these conversations that no PERSON has answered since.
                       "Answered" is the ONE contact rule, work_queue_signals.touch_rows: the AI's own replies and holding lines
                       are not a person's answer; a message a person sent or approved, or a connected call, is.
  ai_already_replied() the AI already told the guest something (a reply it sent alone, or a holding line) after the request.
  ensure_task()        ONE open "Collaboration request" task per conversation, for when no consult took the request.

Callers: agent_consult_flow (reason ``collab_request``: the draft is held, one holding line, the team is told -- the consult is
the work item on My day), concierge_draft (where no consult can open: the task, and no new promise after the first reply), and
the lead autopilot (lead_autopilot_rules: the collab-entry stage; lead_autopilot_service: never auto-Lost while it waits).
Detection is deterministic (lead_auto_create.is_collab_request on the guest's own messages); no LLM call.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, MessageDirection
from app.models.task import Task

log = structlog.get_logger()

TASK_PREFIX = "Collaboration request"
LOOKBACK_MESSAGES = 200


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def pending(db: Session, tenant_id: str, conversation_ids: list, guest_id: Optional[str]) -> Optional[Message]:
    """The oldest collaboration request no person has answered yet, or None."""
    from app.services.lead_auto_create import is_collab_request
    from app.services.work_queue_signals import touch_rows
    ids = [i for i in conversation_ids or [] if i]
    if not ids or not guest_id:
        return None
    rows = (db.query(Message)
            .filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(ids),
                    Message.direction == MessageDirection.INBOUND, Message.is_internal.isnot(True))
            .order_by(Message.created_at.desc()).limit(LOOKBACK_MESSAGES).all())
    asks = [m for m in reversed(rows) if is_collab_request(m.body or "")]            # oldest first
    if not asks:
        return None
    contacts = [at for _, at, kind, _ in touch_rows(db, tenant_id, {guest_id: _aware(asks[0].created_at)}) if kind == "contact"]
    last_contact = max(contacts) if contacts else None
    waiting = [m for m in asks if last_contact is None or _aware(m.created_at) > last_contact]
    return waiting[0] if waiting else None


def pending_for_inquiry(db: Session, tenant_id: str, inquiry) -> Optional[Message]:
    """pending() over the enquiry's conversations and its guest's (the same set the lead autopilot reads)."""
    if inquiry is None or not inquiry.guest_id:
        return None
    conv_ids = [r[0] for r in db.query(Conversation.id).filter(
        Conversation.tenant_id == tenant_id,
        or_(Conversation.inquiry_id == inquiry.id, Conversation.guest_id == inquiry.guest_id)).all()]
    return pending(db, tenant_id, conv_ids, inquiry.guest_id)


def ai_already_replied(db: Session, tenant_id: str, conversation_id: str, since: datetime) -> bool:
    """An AI reply or holding line already went to the guest on this thread after the request."""
    return db.query(Message.id).filter(
        Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
        Message.direction == MessageDirection.OUTBOUND, Message.is_internal.isnot(True),
        Message.sent_autonomously.is_(True), Message.created_at > since,
    ).first() is not None


def ensure_task(db: Session, tenant_id: str, conversation: Conversation, guest, ask: Message) -> Optional[Task]:
    """One open task per conversation; None when it already exists. Flushes; the caller commits.

    Not tied to the enquiry on purpose: moving the lead to the collab stage (a closed stage for lead work) closes and hides the
    enquiry's tasks (lead_task_closer), and this one must stay until a person has answered."""
    existing = (db.query(Task.id)
                .filter(Task.tenant_id == tenant_id, Task.conversation_id == conversation.id, Task.is_done.is_(False),
                        Task.title.ilike(TASK_PREFIX + "%"))
                .first())
    if existing is not None:
        return None
    label = (getattr(guest, "name", None) or "").strip() or "this guest"
    task = Task(tenant_id=tenant_id, title=f"{TASK_PREFIX}: reply yes or no — {label}"[:255], priority="high",
                guest_id=getattr(guest, "id", None) or conversation.guest_id, conversation_id=conversation.id,
                due_date=datetime.now(timezone.utc))
    db.add(task)
    db.flush()
    log.info("collab_request_task_created", tenant_id=tenant_id, conversation_id=conversation.id, task_id=task.id,
             message_id=ask.id)
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(db, tenant_id, title="Collaboration request",
                       body=f"{label} asked about a collaboration. Reply yes or no.",
                       url=f"/dashboard/inbox?conversation={conversation.id}")
    except Exception as exc:  # noqa: BLE001 -- the task is the record; the push is a courtesy
        log.warning("collab_request_push_failed", tenant_id=tenant_id, error=str(exc)[:200])
    return task
