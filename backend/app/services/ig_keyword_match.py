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


# ── Throwaway comments (no AI call) ──────────────────────────────────────────────────────────────────────────────────
# "nice 😍", "wow", "@friend": every unmatched comment used to get an intent call + a reply draft. A comment is throwaway
# when it asks nothing (no "?") and is emoji/punctuation only, or only praise words, or 3 words or fewer with no word a lead
# would use. Workspaces add their own praise words in brand_config["ig_comment_skip_words"] (list or comma string).
_PRAISE_WORDS = frozenset("""
nice wow woww wowww awesome amazing beautiful lovely gorgeous stunning superb super great cool love loved loving lit fab
fabulous fantastic excellent perfect pretty cute mast mazza maza badhiya sundar wah waah osm awsm omg dope fire goals
congrats congratulations thanks thank you thx ty good very so too much place view vibes vibe dream dreamy yes yay hi hello
hey heyy ok okay the this is a an and what wonderful best bro dude sir mam ma'am brother sister wow nice
""".split()) - {"much", "what"}
_LEAD_WORDS = frozenset("""
price prices pricing rate rates cost costs charge charges tariff fare book booking bookings booked available availability
details detail info information dm inbox contact number call whatsapp how much when where which dates date package packages
interested interest location rent rental enquiry inquiry enquire plan trip trips kitna kitne kya kaise kab kaha kahan rates
budget weekend night nights days stay quote
""".split())


def is_throwaway_comment(text: str, extra_skip_words=None) -> bool:
    body = (text or "").strip()
    if not body or "?" in body:
        return not body
    words = re.findall(r"[^\W_]+", body.lower())
    if not words:
        return True                                   # emoji / punctuation only
    if any(w in _LEAD_WORDS for w in words):
        return False
    praise = _PRAISE_WORDS | {w.strip().lower() for w in _keyword_list(extra_skip_words) if w.strip()}
    return len(words) <= 3 or all(w in praise for w in words)
