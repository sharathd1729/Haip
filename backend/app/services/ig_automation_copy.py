"""Copy rules for Instagram automations (Instagram toolkit phase 5): the keyword-delivery DM, its one follow-up, and
public comment replies. Adapted from Jakeschincariol/instagram-agent-skill `ig-dm`, `ig-reply` and `ig-comment` (MIT,
Copyright (c) 2026 Jake Schincariol; docs/marketing-website/THIRD_PARTY_NOTICES.md).

  * Keyword delivery: the thing they asked for FIRST (no "before I send it, can I ask..."), one line on how to use it,
    one short question they can answer in a few words.
  * One follow-up, only after a keyword DM (never after a comment: Instagram allows a single private reply to a
    commenter until they write back), only if the guest has not answered, inside Instagram's 24-hour window.
  * Public replies: no selling and no links, no stock phrases, one idea.
  * Every automated message goes through the phase-1 humanizer at send time (marketing_humanize.clean).
"""
import re
from typing import Optional

from app.services import marketing_humanize as human

DELIVERY_TEMPLATE = "{name}here it is: {thing}.\n\n{how}\n\n{question}"
DEFAULT_FOLLOW_UP = "Did that help? If you tell us your dates, we'll check them for you."
SAFE_PUBLIC_REPLY = "Sent you a DM."
FOLLOW_UP_HOURS, FOLLOW_UP_MAX_HOURS = 20, 23        # Instagram's standard window is 24 h from the guest's message
MAX_DM_CHARS, MAX_PUBLIC_WORDS = 600, 20

URL_RE = re.compile(r"https?://|www\.|\b[a-z0-9-]{2,}\.[a-z]{2,12}\b", re.IGNORECASE)   # any bare domain counts
SELLING_RE = re.compile(r"(?i)(₹|\brs\.?\s?\d|\binr\b|\bprice[sd]?\b|\brates?\b|\bdiscount|\boffer\b|% off|\bbook now\b|"
                        r"\bbook today\b|\blimited (?:time|slots?)\b|\bdeal\b|\bstarting (?:at|from)\b)")
GATE_RE = re.compile(r"(?i)\b(before i send|before we send|can i ask|may i ask|first,? (?:tell|let) me|"
                     r"what do you do|share your (?:email|number))\b")
BANNED_PUBLIC_OPENERS = re.compile(r"(?i)^\s*(great post|love this|so true|needed this|thanks for (?:the )?comment)")


def delivery(thing: str, how: str, question: str, name: Optional[str] = None) -> str:
    """The default keyword-delivery DM, filled in."""
    return DELIVERY_TEMPLATE.format(name=f"{name.strip()}, " if name and name.strip() else "", thing=thing.strip().rstrip("."),
                                    how=how.strip(), question=question.strip())


def _stock(text: str) -> list[str]:
    _, changes = human.clean(text)
    return [c["from"] for c in changes if c["kind"] == "word"]


def _finding(rule: str, message: str, severity: str = "warn") -> dict:
    return {"rule": rule, "status": severity, "message": message}


def check_dm(text: str) -> list[dict]:
    """Rule findings for a keyword-delivery DM (empty = fine). Advisory: the humanizer fixes stock words at send."""
    text = (text or "").strip()
    out = []
    if not text:
        return [_finding("empty", "The DM is empty.", "bad")]
    if GATE_RE.search(text):
        out.append(_finding("gate", "Asks something before delivering. Send what they asked for first, then ask.", "bad"))
    if len(text) > MAX_DM_CHARS:
        out.append(_finding("length", f"{len(text)} characters; keep it under {MAX_DM_CHARS} so it reads on one screen."))
    questions = text.count("?")
    if questions == 0:
        out.append(_finding("question", "No question at the end: one short one starts the conversation."))
    elif questions > 1:
        out.append(_finding("question", f"{questions} questions; keep one short question, at the end."))
    elif not text.rstrip().endswith("?"):
        out.append(_finding("question", "Put the one question last."))
    stock = _stock(text)
    if stock:
        out.append(_finding("stock", f"Stock words: {', '.join(stock[:4])} (fixed automatically when sent)."))
    return out


def check_public_reply(text: str) -> list[dict]:
    """Rule findings for a public comment reply. `bad` ones are never posted (replaced by SAFE_PUBLIC_REPLY)."""
    text = (text or "").strip()
    out = []
    if not text:
        return out
    if URL_RE.search(text):
        out.append(_finding("link", "A link in a public reply: replies never sell. Put it in the DM.", "bad"))
    if SELLING_RE.search(text):
        out.append(_finding("selling", "Sells in public (price, offer, book now). Keep that for the DM.", "bad"))
    if BANNED_PUBLIC_OPENERS.search(text) or _stock(text):
        out.append(_finding("stock", "A stock phrase. Say the one specific thing instead."))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) > 2 or len(text.split()) > MAX_PUBLIC_WORDS:
        out.append(_finding("one_idea", f"More than one idea; keep it to one short line (under {MAX_PUBLIC_WORDS} words)."))
    return out


def prepare_dm(text: str, keep_words=None) -> tuple[str, list[dict]]:
    """The DM as it will be sent: humanized (stock words, dashes, curly quotes, hidden characters)."""
    return human.clean(text, keep_words)


def prepare_public(text: str, keep_words=None) -> tuple[str, list[dict], Optional[str]]:
    """(text to post, humanizer changes, why it was replaced or None). A reply that sells or links is never posted."""
    cleaned, changes = human.clean(text, keep_words)
    bad = [f for f in check_public_reply(cleaned) if f["status"] == "bad"]
    if bad:
        return SAFE_PUBLIC_REPLY, changes, bad[0]["message"]
    return cleaned, changes, None


def follow_up_hours(cfg: dict) -> int:
    try:
        hours = int(cfg.get("follow_up_after_hours") or FOLLOW_UP_HOURS)
    except (TypeError, ValueError):
        hours = FOLLOW_UP_HOURS
    return max(1, min(hours, FOLLOW_UP_MAX_HOURS))


def payload_checks(payload: dict) -> list[dict]:
    """Studio drawer checks for a post's comment-to-DM (phase 1's check list format)."""
    dm = (payload or {}).get("comment_dm") or {}
    if not dm.get("message"):
        return []
    out = []
    dm_findings = check_dm(dm["message"])
    out.append({"key": "keyword_dm", "label": "Keyword DM", "status": max((f["status"] for f in dm_findings), default="ok",
                                                                            key=["ok", "warn", "bad"].index),
                "value": "Delivers first" if not dm_findings else f"{len(dm_findings)} to fix",
                "detail": " ".join(f["message"] for f in dm_findings) or "Delivers what they asked for, then one question."})
    if dm.get("public_reply"):
        pub = check_public_reply(dm["public_reply"])
        out.append({"key": "public_reply", "label": "Public reply", "status": max((f["status"] for f in pub), default="ok",
                                                                                   key=["ok", "warn", "bad"].index),
                    "value": "No selling" if not pub else f"{len(pub)} to fix",
                    "detail": " ".join(f["message"] for f in pub) or "One idea, no selling, no links."})
    return out
