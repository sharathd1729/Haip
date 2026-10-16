"""Safety net: a guest message that never got an AI reply is handed to the concierge again.

Why it exists. A reply is normally queued when the message arrives (a 5-second debounce, then ``tasks.concierge_draft``). That chain has
several single points of failure: a worker restarting during the debounce, the newer task of a message burst dying after the older one
stepped aside ("superseded"), ``MaxRetriesExceededError`` after a crash (it is only logged), a broker hiccup when queueing. In each case
the guest's message sat unanswered with no draft and nothing to notice it, until an agent happened to open the thread.

What it does. Every 10 minutes, per tenant: find open WhatsApp/Instagram threads whose latest guest message is 4 minutes to 6 hours old
and has NO outbound message after it (an AI draft counts: a draft that failed produces a holding reply, so a failing provider does not
make this loop), and queue ``concierge_draft`` for that message. At most once per message per hour, at most 25 per tenant per run.
``concierge_draft`` itself still decides everything (AI off, shadow or autonomous, guards, "already drafted").
"""
from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task
from sqlalchemy import func

from app.core.cache import get_cached, set_cached
from app.core.database import SessionLocal, set_tenant_context
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.tenant import Tenant

log = structlog.get_logger()

MIN_AGE = timedelta(minutes=4)        # give the normal path (debounce + draft + retries) time to finish first
MAX_AGE = timedelta(hours=6)          # older than this the moment has passed; the evening owner report covers those
MAX_PER_TENANT_RUN = 25
ONCE_PER = 3600                       # seconds: never re-queue the same message more than hourly
_CHANNELS = (ChannelType.WHATSAPP, ChannelType.INSTAGRAM)


def _guard_key(message_id: str) -> str:
    return f"haip:reply_recovery:{message_id}"


def missed_replies(db, tenant_id: str, now: datetime) -> list[tuple[str, str]]:
    """[(message_id, conversation_id)] for guest messages that were never answered, oldest first."""
    lo, hi = now - MAX_AGE, now - MIN_AGE
    latest = (db.query(Message.conversation_id, func.max(Message.created_at).label("at"))
              .filter(Message.tenant_id == tenant_id, Message.direction == MessageDirection.INBOUND, Message.is_internal.is_(False),
                      Message.created_at >= lo, Message.created_at <= hi)
              .group_by(Message.conversation_id).all())
    out = []
    for conversation_id, at in latest:
        answered = (db.query(Message.id).filter(Message.conversation_id == conversation_id, Message.direction == MessageDirection.OUTBOUND,
                                                Message.is_internal.is_(False), Message.created_at >= at).first())
        if answered is not None:
            continue
        msg = (db.query(Message).filter(Message.conversation_id == conversation_id, Message.direction == MessageDirection.INBOUND,
                                        Message.is_internal.is_(False), Message.created_at == at).first())
        body = (msg.body or "").strip() if msg else ""
        if msg is None or not body or body.startswith("["):        # media-only / reactions / Instagram "[...]" placeholders: no text to answer
            continue
        out.append((msg.id, conversation_id, at))
    out.sort(key=lambda r: r[2])
    return [(m, c) for m, c, _ in out]


@shared_task(name="concierge.recover_missed_replies")
def recover_missed_replies(tenant_id: str) -> dict:
    from app.services import ai_mode_service
    from app.services.concierge_service import DEBOUNCE_SECONDS, mark_pending_draft
    from app.workers.tasks.concierge_draft import concierge_draft

    db = SessionLocal()
    queued = skipped = 0
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"queued": 0, "skipped": 0}
        for message_id, conversation_id in missed_replies(db, tenant_id, datetime.now(timezone.utc)):
            if queued >= MAX_PER_TENANT_RUN:
                break
            conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first()
            if (conv is None or not conv.is_open or conv.is_sample or conv.channel not in _CHANNELS
                    or ai_mode_service.resolve_mode(tenant, conv) == "off" or get_cached(_guard_key(message_id))):
                skipped += 1
                continue
            set_cached(_guard_key(message_id), "1", ttl=ONCE_PER)
            mark_pending_draft(tenant_id, conversation_id, message_id)
            concierge_draft.apply_async(kwargs={"message_id": message_id, "conversation_id": conversation_id, "tenant_id": tenant_id},
                                        countdown=DEBOUNCE_SECONDS)
            queued += 1
            log.warning("missed_reply_recovered", tenant_id=tenant_id, conversation_id=conversation_id, message_id=message_id)
        return {"queued": queued, "skipped": skipped}
    finally:
        db.close()


@shared_task(name="concierge.recover_missed_replies_all_tenants")
def recover_missed_replies_all_tenants() -> dict:
    """Fan out to every active tenant (beat, every 10 minutes)."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    for tid in tenant_ids:
        recover_missed_replies.delay(tid)
    return {"tenants_queued": len(tenant_ids)}
