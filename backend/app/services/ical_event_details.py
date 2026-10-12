"""Booking details read from a calendar event's title and description.

The Ratha team keeps bookings in one shared Google Calendar. Each event is titled "<guest>| <staff>" (sometimes with the
caravan, "white ratha" / "black Ratha") and the description holds a block of "Label: value" lines (guest, phone,
destination, dates, package, amounts). This module reads that block. It is deliberately forgiving about wording and strict
about what it believes: a value it cannot read is left out, never guessed, and a trip date that disagrees with the event's
own day by more than a week is ignored in favour of the event.

Nothing here touches the database; sync (ical_sync_service) decides what to store and what to block.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9

MAX_NIGHTS = 31
MAX_EVENT_DRIFT = timedelta(days=7)

_LABELS = {  # first matching label wins; longest labels first so "total booking amount" beats "total"
    "guest_name": ("guest name", "name of guest", "guest"),
    "phone": ("contact number", "contact no", "contact", "phone", "mobile"),
    "destination": ("destination", "location", "pickup", "pick up"),
    "dates": ("dates", "date"),
    "vehicle_requirement": ("vehicle requirement",),
    "return": ("return",),
    "vehicles": ("vehicles", "vehicle"),
    "package": ("package",),
    "guests": ("guests", "pax"),
    "package_cost": ("package cost", "rate"),
    "gst": ("gst (18%)", "gst"),
    "total": ("total booking amount", "total amount", "total"),
    "advance": ("advance received", "advance paid", "advance"),
    "balance": ("balance amount", "balance"),
    "booked_on": ("booked on",),
}
_ORDERED = sorted(((lab, key) for key, labs in _LABELS.items() for lab in labs), key=lambda t: -len(t[0]))

_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
_PHONE = re.compile(r"\+?\d[\d\s\-]{8,}\d")
_DATE_FULL = re.compile(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", re.I)
_DATE_RANGE = re.compile(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:-|–|—|to)\s*(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", re.I)


def unescape(text: str) -> str:
    """iCalendar text escaping: \\n, \\, \\; and \\\\."""
    return (text or "").replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _clean_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9()% ]+", "", raw.lower()).strip()


def parse_amount(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = _AMOUNT.search(text)
    if not m:
        bare = re.fullmatch(r"\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*", text)
        m = bare
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _month(name: str) -> Optional[int]:
    return MONTHS.get(name.lower().rstrip("."))


def _make_date(day: str, month_name: str, year: str) -> Optional[date]:
    month = _month(month_name)
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_trip_dates(*texts: str) -> Optional[tuple[date, date]]:
    """(first day, last day) from lines like "20th - 22nd October 2026" or "12th October 2026 ... to 14th October 2026".
    The last day is the day the guests leave, so [first, last) are the nights the vehicle is out."""
    for text in texts:
        if not text:
            continue
        rng = _DATE_RANGE.search(text)
        if rng:
            a = _make_date(rng.group(1), rng.group(3), rng.group(4))
            b = _make_date(rng.group(2), rng.group(3), rng.group(4))
            if a and b:
                return a, b
    found: list[date] = []
    for text in texts:
        for m in _DATE_FULL.finditer(text or ""):
            d = _make_date(m.group(1), m.group(2), m.group(3))
            if d:
                found.append(d)
    if len(found) >= 2 and min(found) < max(found):
        return min(found), max(found)
    return None


def extract(summary: str, description: str) -> dict:
    """Everything readable from one event. Keys with no readable value are absent."""
    desc = unescape(description)
    fields: dict[str, str] = {}
    for raw in desc.split("\n"):
        line = raw.strip()
        if ":" not in line:
            continue
        head, _, value = line.partition(":")
        key = _clean_key(head)
        value = value.strip()
        if not key or not value:
            continue
        for label, name in _ORDERED:
            if key == label or key.startswith(label + " "):
                fields.setdefault(name, value)
                break

    out: dict = {"title": (summary or "").strip()}
    if "guest_name" in fields:
        out["guest_name"] = re.sub(r"^(ms|mr|mrs|miss|dr)\.?\s+", "", fields["guest_name"], flags=re.I).strip()
    if "phone" in fields:
        m = _PHONE.search(fields["phone"])
        if m:
            out["phone"] = re.sub(r"[^\d+]", "", m.group(0))
    for name in ("destination", "package", "guests", "vehicles", "booked_on"):
        if name in fields:
            out[name] = fields[name]
    amounts = {}
    for name in ("package_cost", "gst", "total", "advance", "balance"):
        value = parse_amount(fields.get(name))
        if value is not None:
            amounts[name] = value
    if "total" not in amounts:                         # free-text ending like "Total ₹35,500, fully paid."
        m = re.search(r"\btotal\b[^0-9₹]*?(?:₹|rs\.?)\s*([0-9][0-9,]*)", desc, re.I)
        if m:
            amounts["total"] = float(m.group(1).replace(",", ""))
    if re.search(r"fully paid", desc, re.I) and "total" in amounts:
        amounts.setdefault("advance", amounts["total"])
        amounts.setdefault("balance", 0.0)
    if amounts:
        out["amounts"] = amounts
    trip = parse_trip_dates(fields.get("dates", ""), " ".join(filter(None, [fields.get("vehicle_requirement"), fields.get("return")])))
    if trip:
        out["trip_start"], out["trip_end"] = trip[0].isoformat(), trip[1].isoformat()
    if desc.strip():
        out["notes"] = desc.strip()[:1500]
    return out


def block_window(event_start: str, event_end: str, details: dict) -> tuple[str, str, str]:
    """(from, to-exclusive, source) of the days to block. Uses the trip dates written in the description when they are
    sensible and close to the event's own day, widened to also cover the event itself; otherwise the event's dates."""
    start, end = date.fromisoformat(event_start), date.fromisoformat(event_end)
    if details.get("trip_start") and details.get("trip_end"):
        t_start, t_end = date.fromisoformat(details["trip_start"]), date.fromisoformat(details["trip_end"])
        sane = t_end > t_start and (t_end - t_start).days <= MAX_NIGHTS and abs(t_start - start) <= MAX_EVENT_DRIFT
        if sane:
            return min(start, t_start).isoformat(), max(end, t_end).isoformat(), "description"
    return event_start, event_end, "event"


def match_vehicles(text: str, rules: dict[str, list[str]]) -> list[str]:
    """Property ids whose keywords appear (as whole words, any case) in the title or description. Empty = ambiguous."""
    hits = []
    for property_id, keywords in rules.items():
        for kw in keywords:
            kw = kw.strip()
            if kw and re.search(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])", text, re.I):
                hits.append(property_id)
                break
    return hits
