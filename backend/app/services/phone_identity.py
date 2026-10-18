"""What counts as a usable phone number, and how it is written.

A lead is a person HAIP has a usable phone number for (docs/analytics/KPI_METRIC_CATALOGUE.md, "Lead definition"). Usable means:
a number that parses and is valid for its country (the ``phonenumbers`` library, already a dependency), and is not an obvious
placeholder (all one digit, a run like 1234567890, the empty "+91"). Everything is written as E.164 ("+919845612345").

A number written without a country code is read in the workspace's own country, taken from its configured timezone. That is
a deliberate, narrow default: India is assumed only for a workspace whose timezone is Indian, never for everybody. A workspace
whose country cannot be told gets no default, so a bare 10-digit number stays unusable until it is given with a country code.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import phonenumbers

# Workspace timezone -> the country a bare local number belongs to. Small on purpose: a timezone that is not listed
# gives no default region (numbers must then carry a country code), it never falls back to India.
REGION_BY_TIMEZONE = {
    "Asia/Kolkata": "IN", "Asia/Calcutta": "IN",
    "Asia/Dubai": "AE", "Asia/Singapore": "SG", "Asia/Colombo": "LK", "Asia/Kathmandu": "NP", "Asia/Dhaka": "BD",
    "Europe/London": "GB", "America/New_York": "US", "America/Chicago": "US", "America/Los_Angeles": "US",
    "Australia/Sydney": "AU",
}

_SUFFIX = re.compile(r"@(?:s\.whatsapp\.net|c\.us|g\.us|lid)$", re.I)
_REGION_TTL = 300.0
_region_cache: dict[str, tuple[float, Optional[str]]] = {}


def region_for_timezone(tz: Optional[str]) -> Optional[str]:
    return REGION_BY_TIMEZONE.get(tz or "")


def region_for_tenant(db, tenant_id: str) -> Optional[str]:
    """The workspace's default region, cached for a few minutes (it changes about never)."""
    now = time.monotonic()
    hit = _region_cache.get(tenant_id)
    if hit and now - hit[0] < _REGION_TTL:
        return hit[1]
    from app.models.tenant import Tenant
    row = db.query(Tenant.timezone).filter(Tenant.id == tenant_id).first()
    region = region_for_timezone(row[0] if row else None)
    _region_cache[tenant_id] = (now, region)
    return region


def _is_placeholder(national: str) -> bool:
    """0000000000, 9999999999, 1234567890, 0123456789: numbers nobody owns."""
    digits = re.sub(r"\D", "", national)
    if len(digits) < 6:
        return True
    if len(set(digits)) == 1:
        return True
    ascending = "01234567890123456789"
    descending = ascending[::-1]
    return digits in ascending or digits in descending


def normalize(raw: Optional[str], region: Optional[str] = None) -> Optional[str]:
    """E.164 for a usable phone number, else None. Never raises."""
    if not raw:
        return None
    text = _SUFFIX.sub("", str(raw).strip())
    if not re.search(r"\d", text):
        return None
    if text.startswith("00"):
        text = "+" + text[2:]
    keep = "+" + re.sub(r"\D", "", text) if text.lstrip().startswith("+") else re.sub(r"\D", "", text)
    if not re.sub(r"\D", "", keep):
        return None
    try:
        if keep.startswith("+"):
            number = phonenumbers.parse(keep, None)
        elif region:
            number = phonenumbers.parse(keep, region)
        elif len(keep) >= 11:
            # WhatsApp ids and many exports are international digits without the "+"; read them as such.
            number = phonenumbers.parse("+" + keep, None)
        else:
            return None
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number) or _is_placeholder(str(number.national_number)):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def is_usable(raw: Optional[str], region: Optional[str] = None) -> bool:
    return normalize(raw, region) is not None


# A message longer than this is not a chat message; reading only its start keeps the matcher cheap.
_MAX_SCAN_CHARS = 4000


def find_phones(text: Optional[str], region: Optional[str] = None) -> list[str]:
    """Every usable phone number written in free text (a chat message), as E.164, in order, without repeats.

    Uses the ``phonenumbers`` matcher at VALID leniency rather than a digit regex. The regex this replaced took the FIRST run
    of digits and spaces and stopped there, so it failed on the messages guests actually send: a date before the number
    ("24 10 2026 to 26 10 2026, ph 9876543210"), a date or a head count right after it ("9876543210 21/10 to 22/10",
    "+91 9876543210 2 adults" -- the trailing digits were swallowed into one invalid 12-digit run) and dot separators
    ("98765.43210"). The matcher finds each number on its own and rejects dates, prices ("25,000"), pincodes ("560064") and
    long reference numbers, because none of them is a valid number for the region. Placeholders (9999999999, 1234567890)
    are dropped like everywhere else. ``region`` is the country a number without a country code belongs to; with no region
    only numbers written with a "+" country code are found.
    """
    if not text:
        return []
    found: list[str] = []
    try:
        matcher = phonenumbers.PhoneNumberMatcher(str(text)[:_MAX_SCAN_CHARS], region or "ZZ",
                                                  leniency=phonenumbers.Leniency.VALID)
        for match in matcher:
            number = match.number
            if _is_placeholder(str(number.national_number)):
                continue
            e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
            if e164 not in found:
                found.append(e164)
    except Exception:  # noqa: BLE001 -- free text must never break message ingest
        return found
    return found
