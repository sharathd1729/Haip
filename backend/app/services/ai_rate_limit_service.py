"""Rate limits on autonomous AI sends.

Protects against the AI talking too much, which has two distinct shapes:

  - a loop on one conversation (an out-of-office auto-responder on the
    guest's side, a webhook redelivery storm, or a prompt that keeps
    inviting a reply) -- the guest gets spammed, which on a luxury brand's
    WhatsApp line is worse than silence;
  - a tenant-wide blast, where a bug fans out across many conversations at
    once and nobody notices until guests complain.

Counted from the `messages` table rather than a Redis counter: the limit is
then exact, survives a broker restart, and cannot drift from what actually
reached guests. The queries are indexed (migration 081) and run once per
autonomous send, which is a very low-frequency path.

Hitting a limit never drops the reply -- the draft is still written and
still visible to agents. It only withholds the *automatic send*.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.conversation import Message, MessageDirection

log = structlog.get_logger()

DEFAULT_PER_CONVERSATION_HOUR = 6
DEFAULT_CONSECUTIVE = 3
DEFAULT_PER_TENANT_HOUR = 60


def _limit(tenant, attr: str, fallback: int) -> int:
    val = getattr(tenant, attr, None) if tenant is not None else None
    try:
        val = int(val)
    except (TypeError, ValueError):
        return fallback
    # 0 or negative would silently disable autonomous sending entirely,
    # which is what the kill switch is for -- treat it as unset.
    return val if val > 0 else fallback


def consecutive_ai_replies(db: Session, conversation_id: str) -> int:
    """How many AI messages have gone out since the guest last said anything.

    The single most useful loop signal: a real exchange alternates. Two or
    three AI messages stacked with no guest reply in between means the AI is
    talking to itself.
    """
    recent = (
        db.query(Message.direction, Message.sent_autonomously)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    count = 0
    for direction, autonomous in recent:
        dir_val = getattr(direction, "value", direction)
        if str(dir_val).lower() == "inbound":
            break
        if autonomous:
            count += 1
    return count


def check_send_allowed(
    db: Session, tenant, conversation
) -> Tuple[bool, Optional[str]]:
    """Return (allowed, reason). `reason` is set only when blocked."""
    if conversation is None:
        return True, None

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)

    # 1. Consecutive replies with no guest response -- the loop signal.
    max_consecutive = _limit(tenant, "ai_max_consecutive_replies", DEFAULT_CONSECUTIVE)
    consecutive = consecutive_ai_replies(db, conversation.id)
    if consecutive >= max_consecutive:
        return False, (
            f"{consecutive} consecutive AI replies with no guest response "
            f"(limit {max_consecutive})"
        )

    # 2. Per-conversation hourly cap.
    max_conv = _limit(tenant, "ai_max_sends_per_conversation_hour", DEFAULT_PER_CONVERSATION_HOUR)
    conv_count = (
        db.query(func.count(Message.id))
        .filter(
            Message.conversation_id == conversation.id,
            Message.sent_autonomously.is_(True),
            Message.created_at >= hour_ago,
        )
        .scalar()
    ) or 0
    if conv_count >= max_conv:
        return False, f"{conv_count} AI sends to this guest in the last hour (limit {max_conv})"

    # 3. Tenant-wide hourly cap -- catches a fan-out no single conversation
    #    would reveal.
    tenant_id = getattr(conversation, "tenant_id", None) or getattr(tenant, "id", None)
    if tenant_id:
        max_tenant = _limit(tenant, "ai_max_sends_per_tenant_hour", DEFAULT_PER_TENANT_HOUR)
        tenant_count = (
            db.query(func.count(Message.id))
            .filter(
                Message.tenant_id == tenant_id,
                Message.sent_autonomously.is_(True),
                Message.created_at >= hour_ago,
            )
            .scalar()
        ) or 0
        if tenant_count >= max_tenant:
            return False, f"{tenant_count} AI sends across the workspace in the last hour (limit {max_tenant})"

    return True, None
