"""Parse the text file WhatsApp's "Export chat" makes (pure: no database, no I/O). Used by lead_evidence_service.

Formats handled (both phones, with and without media, any locale WhatsApp ships in India):
  Android   ``12/10/2026, 14:35 - Name: text``   ``12/10/26, 2:35 pm - Name: text``   (dd/mm or mm/dd, 12 h or 24 h)
  iOS       ``[12/10/26, 2:35:12 PM] Name: text``   (often with an invisible U+200E mark first)
  Dates may use / . or -, a 2- or 4-digit year, or start with the year (yyyy-mm-dd). The day/month order is read from
  the whole file (a first number over 12 = day first; a second number over 12 = month first; neither = day first, the
  Indian default); ``date_order`` overrides it.
  A line that does not start with a date belongs to the message above it (multi-line messages).
  System lines (encryption notice, group changes, missed calls, deleted messages) are skipped and counted.
  Media: ``<Media omitted>`` / ``image omitted`` (exported without media) and ``IMG-...jpg (file attached)`` /
  ``<attached: 0001-PHOTO-....jpg>`` (exported with media: the file sits next to _chat.txt in the zip).

Timestamps come back NAIVE: they are the exporting phone's local time; the caller attaches the workspace time zone.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮﻿⁦⁧⁨⁩"), None)
_SPACES = {ord(" "): " ", ord(" "): " ", ord(" "): " "}

_DATE = r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
_TIME = r"(?P<time>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)(?:\s*(?P<ampm>[aApP]\.?\s?[mM]\.?))?"
IOS_LINE = re.compile(rf"^\[{_DATE},?\s+{_TIME}\]\s*(?P<rest>.*)$")
ANDROID_LINE = re.compile(rf"^{_DATE},?\s+{_TIME}\s+[-–]\s+(?P<rest>.*)$")

_ATTACHED_IOS = re.compile(r"<attached:\s*(?P<file>[^>]+)>", re.I)
_ATTACHED_ANDROID = re.compile(r"^(?P<file>[^\n<>:\\/]{1,200}\.[A-Za-z0-9]{2,5})\s+\(file attached\)", re.I)
_OMITTED = re.compile(r"^(?:<media omitted>|<\s*media omitted\s*>|(?:image|video|audio|sticker|gif|document|contact card)\s+omitted)$", re.I)
_EDITED = re.compile(r"\s*<this message was edited>\s*$", re.I)

SYSTEM_PHRASES = (
    "messages and calls are end-to-end encrypted", "messages to this group are now secured", "created group", "created this group",
    "changed the subject", "changed this group's icon", "changed the group description", "joined using this group's invite link",
    "security code changed", "your security code with", "missed voice call", "missed video call", "this message was deleted",
    "you deleted this message", "waiting for this message", "turned on disappearing messages", "turned off disappearing messages",
    "is a contact", "changed their phone number", "blocked this contact", "unblocked this contact", "pinned a message",
)


@dataclass
class ParsedMessage:
    at: datetime                       # naive, the exporting phone's local time
    sender: str
    text: str
    media_file: Optional[str] = None   # a file name inside the zip
    media_omitted: bool = False


@dataclass
class ParseResult:
    messages: list = field(default_factory=list)
    senders: list = field(default_factory=list)    # [(name, count)], most messages first
    system_lines: int = 0
    skipped_lines: int = 0
    date_order: str = "dmy"
    fmt: str = ""                                   # android | ios


def _clean(line: str) -> str:
    return line.translate(_INVISIBLE).translate(_SPACES).rstrip("\r")


def _date_parts(raw: str) -> tuple[int, int, int]:
    a, b, c = (int(p) for p in re.split(r"[./-]", raw))
    return a, b, c


def detect_order(dates: list[str]) -> str:
    """dmy | mdy | ymd for the whole file (see the module docstring)."""
    firsts, seconds, year_first = [], [], 0
    for raw in dates:
        parts = re.split(r"[./-]", raw)
        if len(parts[0]) == 4:
            year_first += 1
            continue
        firsts.append(int(parts[0]))
        seconds.append(int(parts[1]))
    if year_first and not firsts:
        return "ymd"
    if any(a > 12 for a in firsts):
        return "dmy"
    if any(b > 12 for b in seconds):
        return "mdy"
    return "dmy"


def _to_datetime(raw_date: str, raw_time: str, ampm: Optional[str], order: str) -> Optional[datetime]:
    a, b, c = _date_parts(raw_date)
    if len(re.split(r"[./-]", raw_date)[0]) == 4:
        year, month, day = a, b, c
    elif order == "mdy":
        month, day, year = a, b, c
    else:
        day, month, year = a, b, c
    if year < 100:
        year += 2000
    parts = [int(p) for p in re.split(r"[:.]", raw_time)]
    hour, minute, second = parts[0], parts[1], parts[2] if len(parts) > 2 else 0
    if ampm:
        pm = ampm.lower().replace(".", "").replace(" ", "").startswith("p")
        if hour == 12:
            hour = 0
        if pm:
            hour += 12
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


_CONTAINS = ("end-to-end encrypted", "created group", "changed the subject", "changed this group's icon",
             "changed the group description", "joined using this group's invite link", "security code changed",
             "turned on disappearing", "turned off disappearing", "changed their phone number")


def is_system(sender: Optional[str], text: str) -> bool:
    """A line WhatsApp wrote itself (no sender, or a known notice), not a message a person typed."""
    if sender is None:
        return True
    low = " ".join(text.lower().split())
    if not low:
        return False
    return low.startswith(SYSTEM_PHRASES) or (len(low) < 200 and any(p in low for p in _CONTAINS))


def _split_sender(rest: str) -> tuple[Optional[str], str]:
    idx = rest.find(": ")
    if idx <= 0:
        if rest.endswith(":") and len(rest) > 1:
            return rest[:-1].strip().lstrip("~").strip(), ""
        return None, rest
    return rest[:idx].strip().lstrip("~").strip() or None, rest[idx + 2:]


def _media(text: str) -> tuple[str, Optional[str], bool]:
    """(caption, media file, omitted) for one message's text."""
    first, _, tail = text.partition("\n")
    m = _ATTACHED_IOS.search(first)
    if m:
        caption = (first[:m.start()] + first[m.end():]).strip()
        return "\n".join(x for x in (caption, tail.strip()) if x), m.group("file").strip(), False
    m = _ATTACHED_ANDROID.match(first.strip())
    if m:
        return tail.strip(), m.group("file").strip(), False
    if _OMITTED.match(first.strip()):
        return tail.strip(), None, True
    return text, None, False


def parse(content: str, date_order: Optional[str] = None) -> ParseResult:
    """Every message in the export, oldest first (file order)."""
    lines = [_clean(x) for x in content.split("\n")]
    heads: list[tuple[int, re.Match, str]] = []
    for i, line in enumerate(lines):
        m = IOS_LINE.match(line)
        if m:
            heads.append((i, m, "ios"))
            continue
        m = ANDROID_LINE.match(line)
        if m:
            heads.append((i, m, "android"))
    result = ParseResult()
    if not heads:
        result.skipped_lines = len([x for x in lines if x.strip()])
        return result
    result.fmt = Counter(k for _, _, k in heads).most_common(1)[0][0]
    order = date_order if date_order in ("dmy", "mdy", "ymd") else detect_order([m.group("date") for _, m, _ in heads])
    result.date_order = order
    result.skipped_lines = len([x for x in lines[:heads[0][0]] if x.strip()])

    counts: Counter = Counter()
    for n, (i, m, _) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = "\n".join([m.group("rest"), *lines[i + 1:end]]).rstrip()
        at = _to_datetime(m.group("date"), m.group("time"), m.group("ampm"), order)
        if at is None:
            result.skipped_lines += 1
            continue
        sender, text = _split_sender(body)
        text = _EDITED.sub("", text)
        if is_system(sender, text):
            result.system_lines += 1
            continue
        caption, media_file, omitted = _media(text)
        if not caption and not media_file and not omitted:
            result.skipped_lines += 1
            continue
        result.messages.append(ParsedMessage(at=at, sender=sender, text=caption, media_file=media_file, media_omitted=omitted))
        counts[sender] += 1
    result.senders = counts.most_common()
    return result
