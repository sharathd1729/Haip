"""Instagram "seen" (webhook field messaging_seen): the person opened their chat with the business.

Each automation that sent them a DM in the last 7 days, before the moment they opened it, gets one "opened" event for
that person (ig_automation_events), which the automations dashboard counts. Messages written by staff are not
automation DMs and are not counted. Queue: whatsapp.
"""

from datetime import UTC, datetime, timedelta

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()

LOOKBACK = timedelta(days=7)


def record_seen(db, tenant_id: str, sender_id: str, seen_at: datetime) -> int:
    """Log "opened" once per (automation, person) for automation DMs sent before seen_at. Returns how many were new.
    Does not commit."""
    from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
    from app.models.guest_identity import GuestIdentity
    from app.models.ig_automation import IgAutomationEvent

    guest_id = (
        db.query(GuestIdentity.guest_id)
        .filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.identity_type == "instagram_user_id",
            GuestIdentity.identity_value == sender_id,
        )
        .scalar()
    )
    if not guest_id:
        return 0
    rows = (
        db.query(Message.channel_metadata)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Conversation.guest_id == guest_id,
            Conversation.channel == ChannelType.INSTAGRAM,
            Message.direction == MessageDirection.OUTBOUND,
            Message.sender_kind == "automation",
            Message.created_at >= seen_at - LOOKBACK,
            Message.created_at <= seen_at,
        )
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()
    )
    rule_ids = {(m or {}).get("automation_rule_id") for (m,) in rows if isinstance(m, dict)} - {None}
    if not rule_ids:
        return 0
    already = {
        r
        for (r,) in db.query(IgAutomationEvent.rule_id).filter(
            IgAutomationEvent.tenant_id == tenant_id,
            IgAutomationEvent.guest_id == guest_id,
            IgAutomationEvent.kind == "opened",
            IgAutomationEvent.rule_id.in_(rule_ids),
        )
    }
    new = rule_ids - already
    for rule_id in new:
        db.add(IgAutomationEvent(tenant_id=tenant_id, rule_id=rule_id, guest_id=guest_id, kind="opened"))
    return len(new)


@shared_task(name="instagram.message_seen")
def process_instagram_seen(payload: dict):
    from app.models.integration import INSTAGRAM_INBOUND_STATUSES, Integration

    ig_account_id, sender_id = payload.get("ig_account_id") or "", payload.get("sender_id") or ""
    try:
        seen_at = datetime.fromtimestamp(int(payload.get("timestamp")) / 1000, tz=UTC)
    except (TypeError, ValueError):
        seen_at = datetime.now(UTC)
    with SessionLocal() as db:
        try:
            integration = next(
                (
                    i
                    for i in db.query(Integration)
                    .filter(Integration.kind == "instagram", Integration.status.in_(INSTAGRAM_INBOUND_STATUSES))
                    .all()
                    if (i.config or {}).get("instagram_business_account_id") == ig_account_id
                ),
                None,
            )
            if integration is None or not sender_id:
                return {"status": "skipped"}
            set_tenant_context(db, integration.tenant_id)
            n = record_seen(db, integration.tenant_id, sender_id, seen_at)
            db.commit()
            return {"status": "ok", "opened": n}
        except Exception:  # noqa: BLE001 -- a lost "seen" only undercounts opens
            db.rollback()
            log.exception("instagram_seen_failed", ig_account_id=ig_account_id)
            return {"status": "error"}
