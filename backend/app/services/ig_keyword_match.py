"""
T2.2 — Inline keyword matching for Instagram DM/comment auto-replies.

Called directly from process_instagram_dm.py / process_instagram_comment.py
(not through fire_trigger.delay() -- see Architecture Decision #2 in the
Instagram module build plan: the fallback decision needs a synchronous
answer within the same task that decides whether to queue concierge_draft).

Matching is unlimited-keyword, case-insensitive, comma-list or array,
word-boundary regex -- explicitly not Meta's native 5-keyword,
case-sensitive limit (see Architecture Decision #1).
"""

from __future__ import annotations
import re
from typing import Optional
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule

_ACTION = "send_instagram_quick_reply"


def _keyword_list(raw) -> list[str]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        items = []
    return [k.strip().lower() for k in items if k and k.strip()]


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    if not keywords or not text:
        return False
    lowered = text.lower()
    return any(re.search(r"\b" + re.escape(kw) + r"\b", lowered) for kw in keywords)


def find_matching_rule(
    db: Session,
    tenant_id: str,
    trigger: str,  # "ig_dm_received" | "ig_comment_received"
    text: str,
    media_id: Optional[str] = None,
) -> Optional[AutomationRule]:
    """
    Return the first matching active automation_rules row for this
    trigger/text, or None. Does not dispatch anything or log to
    automation_runs -- callers own the send + audit step (T2.3) and the
    decision to skip the AI fallback when a rule matches (T3.1).
    """
    rules = (
        db.query(AutomationRule)
        .filter_by(tenant_id=tenant_id, trigger=trigger, action=_ACTION, is_active=True)
        .all()
    )
    if not rules or not text:
        return None

    def excluded(rule: AutomationRule) -> bool:
        exclude = _keyword_list((rule.trigger_config or {}).get("exclude_keywords"))
        return _contains_keyword(text, exclude)

    def keywords_match(rule: AutomationRule) -> bool:
        keywords = _keyword_list((rule.trigger_config or {}).get("keywords"))
        return _contains_keyword(text, keywords)

    if trigger == "ig_comment_received" and media_id:
        # Priority: post-specific reply_all -> post-specific keyword -> global keyword.
        post_scoped = [r for r in rules if (r.trigger_config or {}).get("media_id") == media_id]
        global_rules = [r for r in rules if not (r.trigger_config or {}).get("media_id")]

        for r in post_scoped:
            if not excluded(r) and (r.trigger_config or {}).get("reply_all"):
                return r
        for r in post_scoped:
            if not excluded(r) and keywords_match(r):
                return r
        for r in global_rules:
            if not excluded(r) and keywords_match(r):
                return r
        return None

    # DMs (and comments without a resolvable media_id): keyword match on
    # active rules for the tenant, first match wins, no post-scoping concept.
    for r in rules:
        if not excluded(r) and keywords_match(r):
            return r
    return None
