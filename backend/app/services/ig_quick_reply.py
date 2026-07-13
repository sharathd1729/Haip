"""
T2.3 — send_instagram_quick_reply action.

Deterministic canned-text/card send for a keyword-matched Instagram DM or
comment. Called inline from the ingest tasks (Architecture Decision #2),
not through fire_trigger -- this is the fast, cheap path that exists
specifically so most FAQ-shaped messages never need to hit
concierge_draft.

For comment-sourced matches, sends BOTH a short public acknowledgement
(comment reply) and a private DM -- DM-only reads as broken on Instagram,
confirmed from the one real reference implementation checked during
build-plan research.

Every dispatch logs to automation_runs for auditability, same as every
other automation action.
"""

from __future__ import annotations
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule, AutomationRun
from app.models.integration import Integration
from app.core.encryption import decrypt_credentials

logger = logging.getLogger(__name__)


def dispatch_quick_reply(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    recipient_id: str,
    guest_id: str,
    conversation_id: str,
    comment_id: Optional[str] = None,
) -> bool:
    """
    Send the rule's canned reply and log the outcome to automation_runs.

    recipient_id is always the Instagram-scoped user ID -- the private DM
    recipient regardless of whether the trigger was a DM or a comment.
    comment_id, if set, additionally triggers the public comment-reply half.

    Returns True if the reply was sent successfully (private DM leg is the
    one that determines success/failure -- the public ack is best-effort
    and logged separately if it fails).
    """
    action_config = rule.action_config or {}
    message = action_config.get("message", "")
    if not message:
        _log_run(db, tenant_id, rule, conversation_id, guest_id, comment_id,
                  status="skipped", detail="No message configured on rule")
        return False

    integration = db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="instagram", status="active"
    ).first()
    if not integration:
        _log_run(db, tenant_id, rule, conversation_id, guest_id, comment_id,
                  status="failed", detail="Instagram integration not connected")
        return False

    creds = decrypt_credentials(integration.credentials_kms_blob)
    access_token = creds.get("access_token", "")
    ig_account_id = (integration.config or {}).get("instagram_business_account_id", "")
    if not access_token or not ig_account_id:
        _log_run(db, tenant_id, rule, conversation_id, guest_id, comment_id,
                  status="failed", detail="Missing access_token or ig_account_id")
        return False

    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    adapter = InstagramGraphAdapter(access_token=access_token, ig_account_id=ig_account_id)

    # Comment-sourced: public ack first (best-effort -- failure here doesn't
    # block the private DM, which is the reply that actually answers the guest).
    if comment_id:
        pool = action_config.get("public_ack_pool") or []
        ack_text = random.choice(pool) if pool else "Check your DMs! 📥"
        try:
            adapter.reply_to_comment(comment_id, ack_text)
        except Exception as exc:
            logger.warning("Public comment ack failed for %s: %s", comment_id, exc)

    try:
        adapter.send_text(recipient_id=recipient_id, text=message)
    except Exception as exc:
        logger.error("send_instagram_quick_reply DM failed for guest %s: %s", guest_id, exc)
        _log_run(db, tenant_id, rule, conversation_id, guest_id, comment_id,
                  status="failed", detail=f"Send failed: {exc}")
        return False

    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(timezone.utc)
    _log_run(db, tenant_id, rule, conversation_id, guest_id, comment_id,
              status="success", detail=f"Sent: {message[:100]}")
    return True


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
