"""Close AI drafts that nobody acted on: outcome "expired", never "rejected" (no person judged them, so the review metrics stay clean).

A pending draft expires when
  (a) a newer guest message superseded it before it could be sent (concierge_draft, inline),
  (b) something else was sent in its conversation after it was written (the send workers, inline; the sweep as a backstop),
  (c) it is older than 24 h (the beat sweep ``ai_drafts.expire_stale_all_tenants``).
Live (Ratha, 1 Nov 2026): 24 drafts waited for review, none was ever approved or rejected, and weeks-old "let me check and get back
to you" drafts kept the leads list's ``pending_draft`` set.

An expired draft is ``was_approved=False`` (so every "still pending" query, ``was_approved IS NULL``, drops it) plus
``channel_status="expired"`` (what tells it apart from a rejected one; a draft has no channel message id, so no Meta status
callback can overwrite it). Messages are never deleted: the inbox shows the text collapsed as "Expired draft".
"""
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import exists, update
from sqlalchemy.orm import Session, aliased

from app.models.conversation import Message, MessageDeliveryState, MessageDirection

log = structlog.get_logger()

EXPIRED = "expired"
MAX_AGE = timedelta(hours=24)
SWEEP_LIMIT = 500                 # per tenant per run; the next run picks up the rest
# The consult's "let me check" holding reply goes out right after the draft it holds: it must not expire that draft.
_NOT_A_LATER_SEND = ("ai_holding",)
_SENT_STATES = (MessageDeliveryState.SENT, MessageDeliveryState.DELIVERED, MessageDeliveryState.READ)


def is_expired(m: Message) -> bool:
    return bool(m.is_ai_generated) and m.was_approved is False and m.channel_status == EXPIRED


def _pending():
    return (Message.direction == MessageDirection.OUTBOUND, Message.is_ai_generated.is_(True), Message.was_approved.is_(None),
            Message.channel_message_id.is_(None), Message.sent_autonomously.isnot(True))


def expire(db: Session, tenant_id: str, conversation_id: str, message_ids: Iterable[str], reason: str) -> list[str]:
    """Expire these drafts of one conversation if they are still pending. ONE guarded UPDATE (a draft approved or rejected in the
    meantime is left alone), an ``expired`` outcome per draft and ONE audit row for the batch. Caller commits."""
    ids = list(message_ids)
    if not ids:
        return []
    done = [r[0] for r in db.execute(
        update(Message)
        .where(*_pending(), Message.tenant_id == tenant_id, Message.conversation_id == conversation_id, Message.id.in_(ids))
        .values(was_approved=False, delivery_state=None, channel_status=EXPIRED)
        .returning(Message.id)
        .execution_options(synchronize_session=False)
    ).all()]
    if not done:
        return []
    from app.core.audit import append_audit
    from app.services.ai_draft_outcomes_service import record_outcome
    for m in db.query(Message).populate_existing().filter(Message.tenant_id == tenant_id, Message.id.in_(done)).all():
        record_outcome(db, tenant_id=tenant_id, draft=m, outcome=EXPIRED, actor_user_id=None, intent=m.ai_intent)
    append_audit(db, tenant_id=tenant_id, action="ai_draft.expired", target_type="conversation", target_id=conversation_id,
                 payload={"actor": "system", "reason": reason, "message_ids": done, "count": len(done)})
    log.info("ai_drafts_expired", tenant_id=tenant_id, conversation_id=conversation_id, reason=reason, count=len(done))
    return done


def after_send(db: Session, message: Message) -> list[str]:
    """Rule (b), inline: ``message`` was just sent, so every pending draft of its conversation written before it is out of date
    (a draft written after it answers something newer and stays). Never raises (a send that worked must not look failed); commits."""
    if message.is_internal or message.sender_kind in _NOT_A_LATER_SEND:
        return []
    try:
        ids = [r[0] for r in db.query(Message.id).filter(
            *_pending(), Message.tenant_id == message.tenant_id, Message.conversation_id == message.conversation_id,
            Message.id != message.id, Message.created_at < message.created_at).all()]
        done = expire(db, message.tenant_id, message.conversation_id, ids, "later_message_sent")
        db.commit()
        return done
    except Exception as exc:  # noqa: BLE001 -- the sweep retries this within the hour
        db.rollback()
        log.warning("ai_draft_expire_after_send_failed", message_id=message.id, error=str(exc)[:200])
        return []


def sweep(db: Session, tenant_id: str, now: Optional[datetime] = None) -> int:
    """Rules (c) and the backstop for (b), for one tenant. Idempotent: an expired draft is no longer pending. Caller commits."""
    now = now or datetime.now(timezone.utc)
    later = aliased(Message)
    sent_after = exists().where(
        later.tenant_id == Message.tenant_id, later.conversation_id == Message.conversation_id,
        later.direction == MessageDirection.OUTBOUND, later.is_internal.is_(False), later.created_at > Message.created_at,
        later.delivery_state.in_(_SENT_STATES), (later.sender_kind.is_(None) | ~later.sender_kind.in_(_NOT_A_LATER_SEND)))
    rows = (db.query(Message.id, Message.conversation_id, Message.created_at < now - MAX_AGE)
            .filter(*_pending(), Message.tenant_id == tenant_id)
            .filter((Message.created_at < now - MAX_AGE) | sent_after)
            .order_by(Message.created_at).limit(SWEEP_LIMIT).all())
    batches: dict[tuple[str, str], list[str]] = {}
    for mid, conv_id, too_old in rows:
        batches.setdefault((conv_id, "older_than_24h" if too_old else "later_message_sent"), []).append(mid)
    return sum(len(expire(db, tenant_id, conv_id, ids, reason)) for (conv_id, reason), ids in batches.items())
