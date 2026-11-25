"""What an Instagram automation sends after its final message (ReplyRush parity, Nov 2026): a photo or video, then one of
our own posts. Both need Instagram's open 24h chat, so for a comment they go after the tap (the private reply allows a
single text message). Best effort: the final message already went out, so a refused extra is logged, never retried."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.ig_automation import IgAutomationEvent

logger = logging.getLogger(__name__)


def wants_extras(cfg: dict) -> bool:
    return bool(cfg.get("attachment") or (cfg.get("share_post") or {}).get("enabled"))


def trigger_media(db: Session, tenant_id: str, rule_id: str, guest_id: str | None) -> str | None:
    """The post this person commented on when the rule started for them (the "triggered" event keeps it)."""
    if not guest_id:
        return None
    row = (
        db.query(IgAutomationEvent.media_id)
        .filter(IgAutomationEvent.tenant_id == tenant_id, IgAutomationEvent.rule_id == rule_id,
                IgAutomationEvent.guest_id == guest_id, IgAutomationEvent.kind == "triggered",
                IgAutomationEvent.media_id.isnot(None))
        .order_by(IgAutomationEvent.created_at.desc())
        .first()
    )
    return row[0] if row else None


def send_extras(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    adapter,
    *,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    media_id: str | None = None,
) -> list[str]:
    """Send the rule's photo/video and shared post, if any. Returns notes for the run log. The caller commits."""
    from app.services import ig_automation as engine
    from app.services.media_storage import get_presigned_media_url

    cfg = rule.action_config or {}
    notes: list[str] = []
    att = cfg.get("attachment") or {}
    if att.get("key"):
        url = get_presigned_media_url(att["key"], expires_in=3600)  # Instagram downloads it within seconds
        label = "[Photo]" if att.get("kind") == "image" else "[Video]"
        try:
            if not url:
                raise RuntimeError("could not make a link to the file")
            result = adapter.send_media(recipient_id, att.get("kind") or "image", url)
            engine._record(db, tenant_id, conversation_id, label, result, rule.id)
            engine.log_event(db, tenant_id, rule.id, "media_sent", guest_id, media_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ig_automation_media_failed rule=%s: %s", rule.id, exc)
            engine.log_event(db, tenant_id, rule.id, "dm_failed", guest_id, media_id, f"media: {str(exc)[:250]}")
            notes.append("photo/video not sent")
    share = cfg.get("share_post") or {}
    post_id = share.get("media_id") or media_id or trigger_media(db, tenant_id, rule.id, guest_id)
    if share.get("enabled") and post_id:
        try:
            result = adapter.send_post(recipient_id, post_id)
            engine._record(db, tenant_id, conversation_id, "[Shared post]", result, rule.id)
            engine.log_event(db, tenant_id, rule.id, "post_shared", guest_id, post_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ig_automation_share_post_failed rule=%s: %s", rule.id, exc)
            engine.log_event(db, tenant_id, rule.id, "dm_failed", guest_id, post_id, f"share post: {str(exc)[:250]}")
            notes.append("post not shared")
    return notes


def public_reply_only(db: Session, tenant_id: str, rule: AutomationRule, ctx: dict, replied: bool) -> bool:
    """A "public reply only" rule (send_dm False) is done once the public reply is posted. The caller commits."""
    from app.services import ig_automation as engine
    from datetime import UTC, datetime

    if not replied:
        engine._log_run(db, tenant_id, rule, "failed", "The public reply could not be posted", ctx)
        return False
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(UTC)
    engine._log_run(db, tenant_id, rule, "success", "Public reply only (no DM)", ctx)
    return True
