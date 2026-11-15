"""
T2.3 — send_instagram_quick_reply action: the entry the ingest tasks call for a keyword-matched Instagram DM, comment,
story reply or mention. The steps (public reply, private reply, follow gate, link button, events) live in
services/ig_automation.py; this wrapper keeps the call sites' signature.

Instagram toolkit phase 5 (ig_automation_copy): the DM and the public reply go through the humanizer
(ig_automation.py); a public reply that sells or links is replaced by a plain one; a DM-keyword rule
with `follow_up` queues ONE follow-up (ig_quick_reply.follow_up), sent only if the guest has not answered.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_credentials
from app.models.automation import AutomationRule, AutomationRun
from app.models.integration import Integration

logger = logging.getLogger(__name__)


def dispatch_quick_reply(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    recipient_id: str,
    guest_id: str,
    conversation_id: str,
    comment_id: Optional[str] = None,
    media_id: Optional[str] = None,
) -> bool:
    """Run the rule for this person. comment_id set = answer with a public reply + Meta's private reply (a plain DM to
    someone who only commented is refused). True when the DM went out."""
    from app.models.guest import Guest
    from app.services import ig_automation

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first() if guest_id else None
    return ig_automation.start(db, tenant_id, rule, recipient_id=recipient_id, guest_id=guest_id,
                               conversation_id=conversation_id, comment_id=comment_id, media_id=media_id, guest=guest)


def _queue_follow_up(tenant_id: str, rule: AutomationRule, recipient_id: str, guest_id: str,
                     conversation_id: str, hours: int) -> str:
    """One follow-up after a keyword DM (never after a comment: Instagram allows one private reply to a commenter).
    Best-effort: a queue outage only loses the follow-up."""
    try:
        from app.workers.tasks.ig_follow_up import send_follow_up
        sent_at = datetime.now(timezone.utc).isoformat()
        send_follow_up.apply_async(args=[tenant_id, rule.id, recipient_id, guest_id, conversation_id, sent_at],
                                   countdown=hours * 3600)
        return f"follow-up in {hours} h unless they reply"
    except Exception as exc:  # noqa: BLE001
        logger.warning("ig follow-up not queued for rule %s: %s", rule.id, exc)
        return "follow-up not queued"


def send_follow_up(db: Session, tenant_id: str, rule_id: str, recipient_id: str, guest_id: str,
                   conversation_id: str, sent_at: str) -> str:
    """Send the rule's one follow-up if the guest has written nothing since the keyword DM and no person has stepped in.
    Returns what happened (logged to automation_runs)."""
    from app.models.conversation import Conversation, Message, MessageDirection
    from app.models.tenant import Tenant
    from app.services import ig_automation_copy as copy_rules
    from app.services.marketing_humanize import keep_words

    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=tenant_id).first()
    text = ((rule.action_config or {}).get("follow_up") or "").strip() if rule is not None else ""
    if rule is None or not rule.is_active or not text:
        return "skipped: rule gone, off, or without a follow-up"
    since = datetime.fromisoformat(sent_at)
    answered = (db.query(Message.id).join(Conversation, Conversation.id == Message.conversation_id)
                .filter(Message.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                        Message.direction == MessageDirection.INBOUND, Message.created_at > since).first())
    from datetime import timedelta
    staff = (db.query(Message.id).filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                                         Message.direction == MessageDirection.OUTBOUND,
                                         Message.created_at > since + timedelta(minutes=2)).first())
    if answered or staff:
        _log_run(db, tenant_id, rule, conversation_id, guest_id, None, status="skipped",
                 detail="Follow-up not sent: the guest replied or someone answered")
        return "skipped: answered"
    integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram", status="active").first()
    if not integration:
        _log_run(db, tenant_id, rule, conversation_id, guest_id, None, status="failed",
                 detail="Follow-up not sent: Instagram integration not connected")
        return "failed: not connected"
    creds = decrypt_credentials(integration.credentials_kms_blob)
    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    adapter = InstagramGraphAdapter(access_token=creds.get("access_token", ""),
                                    ig_account_id=(integration.config or {}).get("instagram_business_account_id", ""))
    text, _changes = copy_rules.prepare_dm(text, keep_words(db.query(Tenant).filter_by(id=tenant_id).first()))
    try:
        adapter.send_text(recipient_id=recipient_id, text=text)
    except Exception as exc:
        _log_run(db, tenant_id, rule, conversation_id, guest_id, None, status="failed", detail=f"Follow-up send failed: {exc}")
        return "failed: send"
    _log_run(db, tenant_id, rule, conversation_id, guest_id, None, status="success", detail=f"Follow-up sent: {text[:100]}")
    return "sent"


def _log_run(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    conversation_id: str,
    guest_id: str,
    comment_id: Optional[str],
    status: str,
    detail: str,
) -> None:
    try:
        run = AutomationRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            automation_id=rule.id,
            automation_name=rule.name,
            status=status,
            trigger_event=rule.trigger,
            context={
                "conversation_id": conversation_id,
                "guest_id": guest_id,
                "comment_id": comment_id,
            },
            detail=detail,
        )
        db.add(run)
        db.commit()
    except Exception as exc:
        logger.warning("Failed to write automation_runs entry: %s", exc)
        db.rollback()
