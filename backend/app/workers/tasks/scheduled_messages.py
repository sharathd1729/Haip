"""tasks `scheduled_messages.send_due` (beat every minute): send the inbox messages an agent scheduled for later.

POST /conversations/{id}/messages with `scheduled_for` stores the message with no delivery state (conversations.py).
This sweep finds the ones whose time has come and hands each to the channel's normal sender (send_whatsapp /
send_instagram_dm), exactly as an immediate send would. Each message is claimed with one guarded UPDATE
(delivery_state NULL -> QUEUED), so two sweeps can never send it twice. A personal-WhatsApp (read-only bridge) thread
or a channel without a sender is marked FAILED with the reason instead. One workspace per transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()

BATCH = 200
TOO_LATE = timedelta(days=7)  # a message due more than a week ago (workers were down) is not sent out of the blue


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def send_due(db, tenant_id: str, now: datetime | None = None, dispatch=None) -> dict:
    """Send this workspace's due scheduled messages. `dispatch(channel, message_id, tenant_id)` defaults to the real
    Celery senders. Returns counts."""
    from app.models.conversation import Conversation, Message, MessageDeliveryState

    now = now or datetime.now(UTC)
    dispatch = dispatch or _dispatch
    rows = (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant_id,
            Message.scheduled_for.isnot(None),
            Message.delivery_state.is_(None),
            Message.is_internal.isnot(True),
        )
        .limit(BATCH)
        .all()
    )
    out = {"sent": 0, "failed": 0}
    for msg in rows:
        when = _when(msg.scheduled_for)
        if when is None or when > now:
            continue
        claimed = (
            db.query(Message)
            .filter(Message.id == msg.id, Message.delivery_state.is_(None))
            .update({Message.delivery_state: MessageDeliveryState.QUEUED}, synchronize_session=False)
        )
        db.commit()
        if not claimed:
            continue  # another sweep took it
        db.refresh(msg)
        conv = db.query(Conversation).filter_by(id=msg.conversation_id, tenant_id=tenant_id).first()
        channel = str(getattr(msg.channel, "value", msg.channel) or "")
        reason = None
        if conv is None:
            reason = "The conversation no longer exists."
        elif conv.is_personal_bridge:
            reason = "Personal WhatsApp conversations are read-only in HAIP; send it from your phone."
        elif now - when > TOO_LATE:
            reason = "Not sent: it was due more than a week ago."
        elif channel not in ("whatsapp", "instagram"):
            reason = f"No sender for channel: {channel}"
        if reason:
            msg.delivery_state = MessageDeliveryState.FAILED
            msg.delivery_error = reason
            db.commit()
            out["failed"] += 1
            continue
        try:
            dispatch(channel, msg.id, tenant_id)
            out["sent"] += 1
        except Exception as exc:  # noqa: BLE001 -- broker down: put it back so the next sweep sends it
            log.error("scheduled_message_dispatch_failed", tenant_id=tenant_id, message_id=msg.id, error=str(exc)[:200])
            msg.delivery_state = None
            db.commit()
            break
    if out["sent"] or out["failed"]:
        log.info("scheduled_messages_swept", tenant_id=tenant_id, **out)
    return out


def _dispatch(channel: str, message_id: str, tenant_id: str) -> None:
    if channel == "whatsapp":
        from app.workers.tasks.send_whatsapp import send_whatsapp

        send_whatsapp.delay(message_id=message_id, tenant_id=tenant_id)
    else:
        from app.workers.tasks.send_instagram_dm import send_instagram_dm

        send_instagram_dm.delay(message_id=message_id, tenant_id=tenant_id)


@celery_app.task(name="scheduled_messages.send_due")
def send_due_all_tenants() -> dict:
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        tenant_ids = [t for (t,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    total = {"sent": 0, "failed": 0}
    for tid in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tid)
            got = send_due(db, tid)
            total = {k: total[k] + got[k] for k in total}
        except Exception as exc:  # noqa: BLE001 -- one workspace must not stop the others
            log.error("scheduled_messages_tenant_failed", tenant_id=tid, error=str(exc)[:200])
        finally:
            db.close()
    return total
