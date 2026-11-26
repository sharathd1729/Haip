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
    return bool(cfg.get("attachment") or (cfg.get("share_post") or {}).get("enabled") or cfg.get("cards"))


def pick_message(cfg: dict) -> str:
    """The final message: the rule's message, or one of its variants at random ("random messages")."""
    import random

    options = [m for m in [cfg.get("message") or "", *(cfg.get("message_variants") or [])] if m.strip()]
    return random.choice(options) if options else ""


def quick_replies(cfg: dict, rule_id: str) -> list[dict] | None:
    """The rule's own tap buttons for the final message (payload igauto:<rule>:qr:<n>), or None."""
    from app.services.ig_automation import PAYLOAD_PREFIX

    qrs = cfg.get("quick_replies") or []
    return [{"content_type": "text", "title": q["title"][:20], "payload": f"{PAYLOAD_PREFIX}{rule_id}:qr:{i}"}
            for i, q in enumerate(qrs)] or None


def answer_quick_reply(db: Session, tenant_id: str, rule: AutomationRule, n: int, adapter, *, recipient_id: str,
                       guest_id: str | None, conversation_id: str | None) -> None:
    """A tap on one of the rule's quick replies: send its text back. The caller commits."""
    from app.services import ig_automation as engine

    qrs = (rule.action_config or {}).get("quick_replies") or []
    if not 0 <= n < len(qrs) or adapter is None:
        return
    try:
        result = adapter.send_text(recipient_id, qrs[n]["reply"])
    except Exception as exc:  # noqa: BLE001
        engine.log_event(db, tenant_id, rule.id, "dm_failed", guest_id, detail=f"quick reply: {str(exc)[:250]}")
        return
    engine._record(db, tenant_id, conversation_id, qrs[n]["reply"], result, rule.id)
    engine.log_event(db, tenant_id, rule.id, "quick_reply", guest_id, detail=qrs[n]["title"])


def paused_until(db: Session, tenant_id: str):
    """When "pause all automations" ends, or None (brand_config.ig_automations.paused_until, ISO time)."""
    from datetime import UTC, datetime

    from app.models.tenant import Tenant

    cfg = (db.query(Tenant.brand_config).filter(Tenant.id == tenant_id).scalar() or {}).get("ig_automations") or {}
    try:
        until = datetime.fromisoformat(cfg.get("paused_until") or "")
    except ValueError:
        return None
    until = until if until.tzinfo else until.replace(tzinfo=UTC)
    return until if until > datetime.now(UTC) else None


def caption_of(db: Session, tenant_id: str, media_id: str | None) -> str | None:
    """A post's caption, only when a "caption code" automation exists (one Graph lookup per post, cached a week)."""
    from app.core import cache
    from app.services import ig_automation as engine

    if not media_id or not db.query(AutomationRule.id).filter(
            AutomationRule.tenant_id == tenant_id, AutomationRule.is_active.is_(True),
            AutomationRule.trigger_config["scope"].as_string() == "caption_code").first():
        return None
    key = f"igcap:{tenant_id}:{media_id}"
    r = cache._client()
    if r is not None:
        try:
            hit = r.get(key)
            if hit is not None:
                return hit if isinstance(hit, str) else hit.decode()
        except Exception:  # noqa: BLE001
            pass
    adapter = engine._adapter(db, tenant_id)
    if adapter is None:
        return None
    try:
        caption = (adapter._get(f"/{media_id}", {"fields": "caption"}) or {}).get("caption") or ""
    except Exception:  # noqa: BLE001 -- the post stays unmatched by codes; other automations still run
        return None
    if r is not None:
        try:
            r.set(key, caption, ex=7 * 86400)
        except Exception:  # noqa: BLE001
            pass
    return caption


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
    cards = cfg.get("cards") or []
    if cards:
        elements = []
        for c in cards[:10]:
            el = {"title": c["title"][:80], "subtitle": (c.get("subtitle") or "")[:80] or " "}
            url = get_presigned_media_url(c["image_key"], expires_in=3600) if c.get("image_key") else None
            if url:
                el["image_url"] = url
            if c.get("buttons"):
                el["buttons"] = [{"type": "web_url", "url": engine.tracked_url(db, tenant_id, rule.id, b["url"]),
                                  "title": b["title"][:20]} for b in c["buttons"][:3]]
            elements.append(el)
        try:
            result = adapter.send_cards(recipient_id, elements)
            engine._record(db, tenant_id, conversation_id, f"[{len(elements)} cards]", result, rule.id)
            engine.log_event(db, tenant_id, rule.id, "cards_sent", guest_id, media_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ig_automation_cards_failed rule=%s: %s", rule.id, exc)
            engine.log_event(db, tenant_id, rule.id, "dm_failed", guest_id, media_id, f"cards: {str(exc)[:250]}")
            notes.append("cards not sent")
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
