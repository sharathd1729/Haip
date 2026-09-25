"""
Bulk import of WhatsApp subscribers from a CSV file.

Replaces the browser doing one HTTP call per row. The rules that matter:
  * numbers are validated (not merely reformatted) so a typo is reported
    instead of quietly stored and later failing at Meta;
  * someone who already opted out is never re-opted-in by an import;
  * the same number twice in one file is one contact;
  * the result says exactly which rows were skipped and why.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import phonenumbers
from sqlalchemy.orm import Session

MAX_ROWS = 20_000
MAX_BYTES = 2_000_000
MAX_TAG_LEN = 40
_CHUNK = 500

_PHONE_HEADERS = {"phone", "mobile", "number", "phone_number", "phonenumber", "whatsapp", "contact", "mobile_number", "cell", "mobile_no", "phone_no"}
_NAME_HEADERS = {"name", "full_name", "fullname", "guest", "guest_name", "customer", "customer_name"}
_TAG_HEADERS = {"tags", "tag", "labels", "label", "segment", "group"}


class ImportError_(ValueError):
    """The file itself can't be used; message is safe to show."""


@dataclass
class ParsedRow:
    row: int                     # line number in the file, 1-based, header included
    raw_phone: str
    name: Optional[str]
    tags: list[str]


@dataclass
class ImportResult:
    total_rows: int = 0
    added: int = 0
    updated: int = 0
    opted_out_skipped: int = 0
    duplicates_in_file: int = 0
    invalid: list[dict] = field(default_factory=list)          # {row, value, reason}
    opted_out: list[dict] = field(default_factory=list)        # {row, value}


def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip()


def _looks_like_phone(cell: str) -> bool:
    digits = sum(ch.isdigit() for ch in cell)
    return digits >= 7 and digits >= len(cell.replace(" ", "")) * 0.6


def parse_csv(content: bytes) -> list[ParsedRow]:
    if not content or not content.strip():
        raise ImportError_("The file is empty.")
    if len(content) > MAX_BYTES:
        raise ImportError_(f"The file is larger than {MAX_BYTES // 1_000_000} MB. Split it into smaller files.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    sample = text[:4096]
    delimiter = max((",", ";", "\t", "|"), key=sample.count) if any(d in sample for d in (",", ";", "\t", "|")) else ","
    lines = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    lines = [(i + 1, [_clean(c) for c in row]) for i, row in enumerate(lines) if any(_clean(c) for c in row)]
    if not lines:
        raise ImportError_("The file has no rows.")

    # A header row is one where no cell looks like a phone number.
    first_no, first = lines[0]
    has_header = not any(_looks_like_phone(c) for c in first)
    phone_i, name_i, tags_i = 0, 1, 2
    data = lines
    if has_header:
        heads = [c.lower().replace(" ", "_") for c in first]
        find = lambda names: next((i for i, h in enumerate(heads) if h in names), None)  # noqa: E731
        p = find(_PHONE_HEADERS)
        if p is None:
            raise ImportError_("Couldn't find a phone column. Name the column 'phone' (or 'mobile' / 'number').")
        phone_i = p
        name_i = find(_NAME_HEADERS)
        tags_i = find(_TAG_HEADERS)
        data = lines[1:]
    if not data:
        raise ImportError_("The file has a header but no contacts.")
    if len(data) > MAX_ROWS:
        raise ImportError_(f"The file has {len(data):,} rows. The limit is {MAX_ROWS:,} per import.")

    def cell(row, i):
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for line_no, row in data:
        raw_tags = cell(row, tags_i)
        tags = [t.strip() for t in raw_tags.replace(";", "|").replace(",", "|").split("|") if t.strip()]
        out.append(ParsedRow(row=line_no, raw_phone=cell(row, phone_i), name=cell(row, name_i) or None, tags=tags))
    return out


def validate_phone(raw: str) -> tuple[Optional[str], Optional[str]]:
    """(E.164 number, None) or (None, reason)."""
    value = (raw or "").strip()
    if not value:
        return None, "No phone number."
    if "e+" in value.lower():
        return None, "The number was mangled by a spreadsheet (scientific notation). Format the column as text and export again."
    try:
        parsed = phonenumbers.parse(value, "IN")
    except phonenumbers.NumberParseException:
        return None, "Not a phone number."
    if not phonenumbers.is_valid_number(parsed):
        return None, "Not a valid phone number."
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), None


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def import_rows(
    db: Session,
    tenant_id: str,
    rows: list[ParsedRow],
    batch_tag: Optional[str] = None,
    source: str = "import",
) -> ImportResult:
    from app.api.v1.endpoints.messaging import WASubscriber
    from app.models.guest import Guest

    result = ImportResult(total_rows=len(rows))
    tag = (batch_tag or "").strip()[:MAX_TAG_LEN] or None

    # 1. validate + de-duplicate inside the file (first occurrence wins, tags merge)
    by_phone: dict[str, ParsedRow] = {}
    for r in rows:
        phone, problem = validate_phone(r.raw_phone)
        if problem:
            result.invalid.append({"row": r.row, "value": r.raw_phone, "reason": problem})
            continue
        if phone in by_phone:
            result.duplicates_in_file += 1
            for t in r.tags:
                if t not in by_phone[phone].tags:
                    by_phone[phone].tags.append(t)
            continue
        by_phone[phone] = ParsedRow(row=r.row, raw_phone=phone, name=r.name, tags=list(r.tags))

    phones = list(by_phone)
    existing: dict[str, "WASubscriber"] = {}
    guests: dict[str, str] = {}
    for chunk in _chunks(phones, _CHUNK):
        for s in db.query(WASubscriber).filter(WASubscriber.tenant_id == tenant_id, WASubscriber.phone.in_(chunk)):
            existing[s.phone] = s
        for g in db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.is_deleted.is_(False), Guest.phone.in_(chunk)):
            guests[g.phone] = g.id

    now = datetime.now(timezone.utc).isoformat()
    from app.models.base import gen_uuid
    for phone, r in by_phone.items():
        tags = list(r.tags)
        if tag and tag not in tags:
            tags.append(tag)
        sub = existing.get(phone)
        if sub is None:
            db.add(WASubscriber(
                id=gen_uuid(), tenant_id=tenant_id, phone=phone, name=r.name, opted_in=True,
                opt_in_at=now, opt_out_at=None, source=source, tags=tags, guest_id=guests.get(phone),
            ))
            result.added += 1
        elif not sub.opted_in:
            # They opted out. A file from a spreadsheet is not consent.
            result.opted_out_skipped += 1
            if len(result.opted_out) < 200:
                result.opted_out.append({"row": r.row, "value": phone})
        else:
            merged = list(dict.fromkeys([*(sub.tags or []), *tags]))
            changed = merged != list(sub.tags or [])
            sub.tags = merged
            if not sub.name and r.name:
                sub.name, changed = r.name, True
            if not sub.guest_id and guests.get(phone):
                sub.guest_id, changed = guests[phone], True
            if changed:
                result.updated += 1

    result.invalid = result.invalid[:200]
    db.flush()
    return result
