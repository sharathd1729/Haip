"""Answer the comments a post already has with one comment automation ("send back to existing comments", ReplyRush
parity, Nov 2026). Instagram allows a comment's private reply for 7 days, so only comments from the last 7 days count.

For each comment the rule matches (its own keywords / @mention / exclusions, ig_keyword_match.rule_matches):
  * HAIP already has the comment (the webhook stored it): run the rule for that person (ig_automation.start). start()
    answers a comment at most once (Redis key per comment), so a comment the automation already answered is skipped, and
    one a person answered privately comes back from Instagram as "already has a reply" (also skipped);
  * HAIP never saw it (before the account was connected): feed it to the normal comment intake with backfill=True (no
    "new comment" push), which stores it, matches and answers it like a live comment.

The workspace's hourly cap (ig_automation.TENANT_HOURLY_CAP) still applies; what it stops is reported as skipped.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
MAX_COMMENTS = 200  # per run, across the rule's posts
MAX_POSTS = 12  # an "any post" rule: the account's posts from the last 7 days, newest first
MAX_PAGES = 20  # of 50 comments, per post


def _when(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None


def _posts(adapter, rule: AutomationRule, since: datetime) -> list[str]:
    cfg = rule.trigger_config or {}
    if cfg.get("media_id"):  # a post rule, or a "next post" rule once bound
        return [cfg["media_id"]]
    scope = cfg.get("scope") or "any"
    if scope not in ("any", "caption_code"):
        return []  # a "next post" rule not bound yet has no post
    from app.services.ig_keyword_match import caption_has_code

    return [m["id"] for m in adapter.get_recent_media(limit=MAX_POSTS)
            if m.get("id") and (_when(m.get("timestamp")) or since) >= since
            and (scope == "any" or caption_has_code(m.get("caption"), cfg.get("caption_code")))]


def is_comment_rule(rule: AutomationRule) -> bool:
    """A post-comment automation, or a global one that covers comments."""
    return rule.trigger == "ig_comment_received" or (
        rule.trigger == "ig_global" and "comment" in ((rule.trigger_config or {}).get("surfaces") or []))


def run(db: Session, tenant_id: str, rule_id: str, now: datetime | None = None) -> dict:
    """Answer the rule's existing comments. Returns counts: comments read, matched, answered, queued, skipped."""
    from app.models.conversation import Conversation, Message
    from app.models.guest import Guest
    from app.services import ig_automation
    from app.services.ig_keyword_match import rule_matches
    from app.workers.tasks.process_instagram_comment import process_instagram_comment

    out = {"read": 0, "matched": 0, "answered": 0, "queued": 0, "skipped": 0}
    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=tenant_id, is_active=True).first()
    if rule is None or not is_comment_rule(rule):
        return {**out, "status": "not_a_comment_automation"}
    adapter = ig_automation._adapter(db, tenant_id)
    if adapter is None:
        return {**out, "status": "instagram_not_connected"}
    now = now or datetime.now(UTC)
    since = now - WINDOW
    own = adapter._account_id
    for media_id in _posts(adapter, rule, since):
        after = None
        for _page in range(MAX_PAGES):
            if out["read"] >= MAX_COMMENTS:
                break
            comments, after = adapter.list_comments(media_id, after=after)
            for c in comments:
                author = (c.get("from") or {}).get("id")
                at = _when(c.get("timestamp"))
                if not c.get("id") or not author or author == own or (at and at < since):
                    continue
                out["read"] += 1
                if not rule_matches(rule, c.get("text") or ""):
                    continue
                out["matched"] += 1
                stored = db.query(Message).filter_by(tenant_id=tenant_id, channel_message_id=f"comment_{c['id']}").first()
                if stored is None:
                    process_instagram_comment.delay({
                        "ig_account_id": own, "sender_id": author, "comment_id": c["id"], "text": c.get("text") or "",
                        "media_id": media_id, "sender_username": c.get("username") or "", "backfill": True,
                    })
                    out["queued"] += 1
                    continue
                conv = db.query(Conversation).filter_by(id=stored.conversation_id, tenant_id=tenant_id).first()
                guest = db.query(Guest).filter_by(id=conv.guest_id, tenant_id=tenant_id).first() if conv else None
                sent = ig_automation.start(db, tenant_id, rule, recipient_id=author, guest_id=guest.id if guest else None,
                                           conversation_id=conv.id if conv else None, comment_id=c["id"],
                                           media_id=media_id, guest=guest)
                out["answered" if sent else "skipped"] += 1
            if not after or (comments and (_when(comments[-1].get("timestamp")) or now) < since):
                break  # newest first: past the 7-day window, the rest are older
    return {**out, "status": "done"}
