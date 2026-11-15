"""Instagram caption checks: what the feed shows before "... more", one ask, the 5-hashtag cap, search words, prices.

Adapted from Jakeschincariol/instagram-agent-skill `skills/ig-caption/caption.py` (MIT, Copyright (c) 2026 Jake
Schincariol; docs/marketing-website/THIRD_PARTY_NOTICES.md); the asks are rewritten for a hospitality brand ("DM us",
"WhatsApp us", "comment STAY"). Advice only: nothing here blocks saving (the price rule is enforced by
marketing_content_service.check_text; this only reports it).

The 125-character cut is an approximation: the real one moves with the device, font size and line breaks.
"""

import re

TRUNCATE = 125
HASHTAG_LIMIT = 5  # Instagram's cap per post or reel since 18 Dec 2025 (down from 30)

HASHTAG_RE = re.compile(r"(?:^|\s)(#[\w\u0900-\u097f]+)")
ASKS = [
    (re.compile(r"(?i:\bcomment\b)\s+(?:(?i:the word)\s+)?[\"'\u201c]?[A-Z0-9]{2,}\b"), "comment a keyword"),
    (re.compile(r"(?i)\b(?:dm|message|whatsapp|text)\s+(?:us|me)\b"), "message us"),
    (re.compile(r"(?i)\blink in (?:our |my |the )?bio\b"), "link in bio"),
    (re.compile(r"(?i)\bcall us\b|\bgive us a (?:call|ring)\b"), "call us"),
    (re.compile(r"(?i)\bbook (?:now|today|your|a)\b"), "book"),
    (re.compile(r"(?i)\bsave (?:this|it)\b"), "save this"),
    (re.compile(r"(?i)\bshare (?:this|it)\b"), "share this"),
    (re.compile(r"(?i)\bfollow (?:us|me|for)\b"), "follow"),
    (re.compile(r"(?i)\btag (?:someone|a friend|your)\b"), "tag someone"),
    (re.compile(r"(?i)\btell us\b|\bwhich one\b|\bwhat would you\b"), "answer a question"),
]
FILLER_TAGS = {
    "#viral",
    "#fyp",
    "#explore",
    "#explorepage",
    "#foryou",
    "#foryoupage",
    "#trending",
    "#instagood",
    "#love",
    "#follow",
    "#like4like",
    "#reels",
    "#reelsinstagram",
    "#viralreels",
    "#instadaily",
}


def posted_caption(payload: dict) -> str:
    """The caption text Instagram receives: the same join the publisher uses (marketing_publish_service._caption)."""
    tags = " ".join(payload.get("hashtags") or [])
    return (payload.get("caption") or "") + (f"\n\n{tags}" if tags else "")


def visible_window(text: str, cut: int = TRUNCATE) -> tuple[str, bool]:
    """(what the feed shows, whether "... more" follows). Instagram cuts mid-word, so this does too."""
    flat = (text or "").strip()
    return (flat, False) if len(flat) <= cut else (flat[:cut], True)


def _check(key, label, status, value, detail):
    return {"key": key, "label": label, "status": status, "value": value, "detail": detail}


def check_caption(
    caption: str, hashtags: list | None = None, keywords: list | None = None, cut: int = TRUNCATE
) -> dict:
    """Checks on one caption. status: ok | warn | bad."""
    caption = (caption or "").strip()
    tags: list[str] = []
    for t in [*(hashtags or []), *HASHTAG_RE.findall(caption)]:
        t = "#" + str(t).lstrip("#")
        if t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    visible, truncated = visible_window(posted_caption({"caption": caption, "hashtags": hashtags or []}), cut)
    first_line = caption.split("\n", 1)[0].strip()
    checks = []

    if not first_line:
        checks.append(
            _check(
                "visible_line",
                'Visible line before "... more"',
                "bad",
                f"0 / {cut}",
                "The caption opens on a blank line.",
            )
        )
    elif first_line[0] in "#@":
        checks.append(
            _check(
                "visible_line",
                'Visible line before "... more"',
                "bad",
                f"{len(first_line)} / {cut}",
                "Opens on a hashtag or a mention: the one place worth a sentence.",
            )
        )
    elif len(first_line) > cut:
        checks.append(
            _check(
                "visible_line",
                'Visible line before "... more"',
                "warn",
                f"{len(first_line)} / {cut}",
                f"The first line is cut at {cut} characters, mid-thought. Put the hook in the first {cut}.",
            )
        )
    else:
        checks.append(
            _check(
                "visible_line",
                'Visible line before "... more"',
                "ok",
                f"{len(first_line)} / {cut}",
                "The first line shows whole in the feed.",
            )
        )

    found = []
    for pattern, name in ASKS:
        m = pattern.search(caption)
        if m:
            found.append((name, m.group(0)))
    if len(found) == 1:
        checks.append(_check("one_ask", "One clear ask", "ok", found[0][1], f"One call to action: {found[0][0]}."))
    elif not found:
        checks.append(
            _check("one_ask", "One clear ask", "warn", "None", "No call to action. Say what people should do next.")
        )
    else:
        checks.append(
            _check(
                "one_ask",
                "One clear ask",
                "warn",
                f"{len(found)} asks",
                f"{', '.join(n for n, _ in found)}. Two asks work like none: keep one.",
            )
        )

    filler = [t for t in tags if t.lower() in FILLER_TAGS]
    if len(tags) > HASHTAG_LIMIT:
        checks.append(
            _check(
                "hashtags",
                "Hashtags",
                "bad",
                f"{len(tags)} / {HASHTAG_LIMIT}",
                f"Over Instagram's cap of {HASHTAG_LIMIT}: tags past the fifth do not count.",
            )
        )
    elif filler:
        checks.append(
            _check(
                "hashtags",
                "Hashtags",
                "warn",
                f"{len(tags)} / {HASHTAG_LIMIT}",
                f"{', '.join(filler[:3])} describe nothing. Spend the tags on places and topics.",
            )
        )
    else:
        checks.append(
            _check(
                "hashtags",
                "Hashtags",
                "ok",
                f"{len(tags)} / {HASHTAG_LIMIT}",
                " ".join(tags) if tags else "No hashtags.",
            )
        )

    words = [k.strip() for k in keywords or [] if k and k.strip()]
    if words:
        low = caption.lower()
        hit = [k for k in words if k.lower() in low]
        missing = [k for k in words if k.lower() not in low]
        checks.append(
            _check(
                "search_words",
                "Search words",
                "ok" if not missing else "warn",
                f"{len(hit)} / {len(words)}",
                ("Missing: " + ", ".join(missing) + ". People search Instagram by place.")
                if missing
                else "Found: " + ", ".join(hit) + ".",
            )
        )

    return {
        "visible": visible,
        "truncated": truncated,
        "cut": cut,
        "first_line_chars": len(first_line),
        "hashtags": tags,
        "asks": [n for n, _ in found],
        "checks": checks,
    }


def price_check(price_mode: str, strings: list[str]) -> dict:
    from app.services import price_policy

    if price_mode != "handoff":
        return _check("price", "Price policy", "ok", "Prices allowed", "This workspace may state exact live prices.")
    for s in strings:
        found = price_policy.detect_price(s)
        if found:
            return _check(
                "price", "Price policy", "bad", "Mentions a price", f"{found!r}: this workspace never shows prices."
            )
    return _check("price", "Price policy", "ok", "No prices", "No prices, as this workspace's policy says.")


def search_words(profile: dict) -> list[str]:
    """Where people search from: the profile's city and region (shortcut: no per-post keyword list yet)."""
    return [w for w in (profile.get("city"), profile.get("region")) if isinstance(w, str) and w.strip()]


def report(price_mode: str, profile: dict, kind: str, payload: dict) -> dict:
    """All caption checks for one content payload. A story has no caption: only the price check applies."""
    from app.schemas.marketing import strings_of

    payload = payload or {}
    out = (
        check_caption(payload.get("caption") or "", payload.get("hashtags") or [], search_words(profile))
        if "caption" in payload and kind != "article"
        else {
            "visible": None,
            "truncated": False,
            "cut": TRUNCATE,
            "first_line_chars": 0,
            "hashtags": [],
            "asks": [],
            "checks": [],
        }
    )
    from app.services.ig_automation_copy import payload_checks

    out["checks"].extend(payload_checks(payload))  # comment-to-DM copy rules (Instagram toolkit phase 5)
    out["checks"].append(price_check(price_mode, strings_of(payload)))
    return out
