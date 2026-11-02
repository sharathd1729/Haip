"""The guest asked for a person: the AI stops on this thread and a person owns the callback.

Real case (Ratha, 31 Oct 2026): a guest wrote "NO AI please.. human someone call" and then "STOP". The AI acknowledged once
(fine), but afterwards the thread's AI switch was still on, an older AI draft was still waiting with Approve/Edit (one tap
would have sent AI text after STOP), and nobody owned the lead, so nobody owned the callback.

``turn_off`` is the one place that handles it, for every trigger (a whole-message STOP in the WhatsApp webhook, the concierge
extraction's ``wants_human``, the escalation policy's ``human_request`` category):

1. ``conversations.ai_mode = "off"`` -- the same field the Inbox "AI on" switch writes, so the switch shows it and a person can
   turn it back on;
2. every still-pending AI draft in the thread is withdrawn with the Inbox's guarded reject condition (``was_approved`` NULL,
   never sent), so approving it later is a 409 ``draft_rejected``; the draft of the current turn (the acknowledgement) can be
   kept;
3. one audit row ``conversation.ai_turned_off`` (actor system, payload reason) -- the Inbox reads it back for its banner;
4. the lead gets an owner through ``lead_assignment_service.assign_new_lead`` (same rule as a new lead: manual mode or out of
   hours assigns nobody), and ONE high-priority "Call back" task (reused if one is open) + a push to the owner, or to every
   owner/manager when there is none.

STOP means only "no more AI/automated messages". People can still reply; marketing consent is handled elsewhere
(opt_out_responder) and this never touches it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, MessageDirection

log = structlog.get_logger()

AUDIT_ACTION = "conversation.ai_turned_off"
REASONS = {
    "guest_stop": "guest said STOP",
    "wants_human": "guest asked for a person",
    "human_request": "guest asked for a person",
}

# A STOP that turns the AI off must be the WHOLE message. opt_out_detector also matches single words inside a sentence
# ("cancel my booking", "our first stop is Hubli") -- docs/ai/SALES_AGENT_CURRENT_STATE.md §2 item 2 -- and those must not
# switch the AI off as well. "cancel" / "end" / "remove" / "block" / "quit" are left out even as a whole message: too often
# they are about a booking, not about us.
_STOP_WORDS = frozenset(
    {
        "stop",
        "unsubscribe",
        "opt out",
        "optout",
        "stop messages",
        "stop messaging",
        "band karo",
        "बंद करो",
        "रोको",
        "roko",
    }
)


def is_stop_message(text: str | None) -> bool:
    """True when the whole message is a STOP keyword (case, spaces and punctuation around it ignored)."""
    # Punctuation only: a \W class would also strip Devanagari vowel signs ("बंद करो").
    words = re.sub(r"[!-/:-@\[-`{-~…।]+", " ", (text or "").lower()).split()
    return " ".join(words) in _STOP_WORDS


def turn_off(
    db: Session, tenant, conversation: Conversation, reason: str, *, keep_message_id: str | None = None, guest=None
) -> bool:
    """Apply the handoff (see module doc) and commit. False when nothing changed (AI already off, no pending draft)."""
    already_off = (conversation.ai_mode or "").lower() == "off"
    conversation.ai_mode = "off"
    conds = [
        Message.tenant_id == tenant.id,
        Message.conversation_id == conversation.id,
        Message.direction == MessageDirection.OUTBOUND,
        Message.is_ai_generated.is_(True),
        Message.was_approved.is_(None),
        Message.channel_message_id.is_(None),
    ]
    if keep_message_id:
        conds.append(Message.id != keep_message_id)
    withdrawn = db.execute(
        update(Message)
        .where(*conds)
        .values(was_approved=False, delivery_state=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if already_off and not withdrawn:
        db.commit()
        return False

    from app.core.audit import append_audit

    append_audit(
        db,
        tenant_id=tenant.id,
        action=AUDIT_ACTION,
        actor_user_id="system",
        target_type="conversation",
        target_id=conversation.id,
        payload={"reason": reason, "drafts_withdrawn": withdrawn},
    )
    try:
        _callback(db, tenant, conversation, guest)
    except Exception as exc:  # noqa: BLE001 -- the AI must still go off when the task/push fails
        log.warning("ai_handoff_callback_failed", conversation_id=conversation.id, error=str(exc)[:200])
    db.commit()
    log.info(
        "ai_turned_off_guest_asked",
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        reason=reason,
        drafts_withdrawn=withdrawn,
    )
    return True


def _callback(db: Session, tenant, conversation: Conversation, guest) -> None:
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.models.task import Task
    from app.models.user import User, UserRole
    from app.services import lead_assignment_service
    from app.services.push_service import send_to_tenant

    inquiry = (
        db.query(Inquiry).filter_by(id=conversation.inquiry_id, tenant_id=tenant.id).first()
        if conversation.inquiry_id
        else None
    )
    owner = getattr(inquiry, "assigned_to", None) or conversation.assigned_to
    if inquiry is not None and not owner:
        owner = lead_assignment_service.assign_new_lead(db, inquiry, tenant)

    guest = guest or db.query(Guest).filter_by(id=conversation.guest_id, tenant_id=tenant.id).first()
    name = (getattr(guest, "name", None) or "A guest").strip()
    now = datetime.now(UTC)
    # One open callback per guest, the same rule the lead playbooks use (lead_playbook_engine._callback_task).
    task = (
        db.query(Task)
        .filter(
            Task.tenant_id == tenant.id,
            Task.guest_id == conversation.guest_id,
            Task.is_done.is_(False),
            Task.title.ilike("Call back%"),
        )
        .first()
    )
    if task is None:
        db.add(
            Task(
                tenant_id=tenant.id,
                title=f"Call back — {name} asked for a person"[:255],
                priority="high",
                kind="call",
                guest_id=conversation.guest_id,
                inquiry_id=getattr(inquiry, "id", None),
                conversation_id=conversation.id,
                assigned_to=owner,
                due_date=now,
            )
        )
    else:
        task.priority, task.due_date = "high", now
        task.assigned_to = task.assigned_to or owner
    db.flush()

    recipients = (
        [owner]
        if owner
        else [
            u.id
            for u in db.query(User.id)
            .filter(
                User.tenant_id == tenant.id, User.is_active.is_(True), User.role.in_([UserRole.OWNER, UserRole.MANAGER])
            )
            .all()
        ]
    )
    for user_id in recipients:
        send_to_tenant(
            db,
            tenant.id,
            title="Guest asked for a person",
            body=f"{name} wants a call from a person. AI is off on this chat.",
            url=f"/dashboard/inbox?conversation={conversation.id}",
            tag=f"haip-handoff-{conversation.id}",
            user_id=user_id,
        )


def off_reason(db: Session, tenant_id: str, conversation: Conversation) -> str | None:
    """Why the AI is off on this thread, when the guest switched it off: the latest AI on/off audit row is ours. None
    otherwise (AI on, or a person switched it off). Only queried while the AI is off."""
    if (conversation.ai_mode or "").lower() != "off":
        return None
    from app.models.audit_event import AuditEvent

    row = (
        db.query(AuditEvent.action, AuditEvent.payload)
        .filter(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.target_type == "conversation",
            AuditEvent.target_id == conversation.id,
            AuditEvent.action.in_((AUDIT_ACTION, "conversation.ai_toggled")),
        )
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    if row is None or row.action != AUDIT_ACTION:
        return None
    return REASONS.get((row.payload or {}).get("reason"), "guest asked for a person")
