"""iCal calendar sync: read another calendar's reservations into HAIP, and
publish HAIP's own calendar for a property.

Import (their calendar -> HAIP). The feed is fetched, its events become
BlockedDate rows marked "ical:<feed id>:<uid>", and rows whose event has
disappeared are lifted, so a cancellation on Airbnb frees the dates here. Only
dates are known: OTAs do not put guest names or prices in an iCal feed.

Export (HAIP -> their calendar). A public URL per link serves the property's
bookings and blocks as all-day "Reserved" / "Blocked" events, with no guest
details. Imported blocks from the OTHER links of the same property are included
(so a Booking.com reservation closes the dates on Airbnb) but never the link's
own, which would echo a reservation back to the calendar it came from.

iCal is one-way per URL and the other side decides when to re-read it (Airbnb:
a few hours, Google subscriptions: up to a day), so this is availability sync,
not instant sync.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_credentials
from app.core.url_safety import safe_get
from app.services import ical_event_details

log = structlog.get_logger()

# UID domain on everything HAIP publishes. An imported event carrying it is our
# own reservation coming back (some calendars re-publish what they import) and
# must not become a block, or a booking would block itself.
UID_SUFFIX = "@haip"

IMPORT_REASON = "offline_booking"           # existing BlockedDate reason: booked elsewhere
_PAST_WINDOW = timedelta(days=30)           # history older than this is not imported
_EXPORT_PAST = timedelta(days=7)
_MAX_BYTES = 5_000_000
_FEED_CAP_PER_PROPERTY = 10
_FEED_ID_NOTE = re.compile(r"^ical:([0-9a-f-]{36}):")


def new_export_token() -> str:
    return secrets.token_urlsafe(32)


def marker(feed_id: str) -> str:
    return f"ical:{feed_id}:"


# ─── Parsing ──────────────────────────────────────────────────────────────────

def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the previous."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _value_to_date(prop: str, params: dict, value: str, tz: ZoneInfo):
    """(date, time_or_None) for a DTSTART/DTEND value."""
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or (len(value) == 8 and value.isdigit()):
        return datetime.strptime(value[:8], "%Y%m%d").date(), None
    fmt = "%Y%m%dT%H%M%S"
    stamp = value.rstrip("Z")
    dt = datetime.strptime(stamp, fmt)
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz)
    elif params.get("TZID"):
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"])).astimezone(tz)
        except Exception:  # noqa: BLE001  -- unknown/Windows tz name: treat as local
            dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.replace(tzinfo=tz)                   # floating time = tenant local
    return dt.date(), dt.time()


def parse_ics(text: str, tz: ZoneInfo) -> list[dict]:
    """[{uid, start, end, summary}] with start/end as YYYY-MM-DD, end exclusive.
    Cancelled events and events with no usable dates are dropped. Timed events
    cover every local day they touch."""
    events, current = [], None
    for line in _unfold(text):
        up = line.strip().upper()
        if up == "BEGIN:VEVENT":
            current = {"_p": {}}
        elif up == "END:VEVENT" and current is not None:
            ev = current
            current = None
            if (ev.get("STATUS") or "").upper() == "CANCELLED":
                continue
            try:
                if "DTSTART" not in ev:
                    continue
                s_date, s_time = _value_to_date("DTSTART", ev["_p"].get("DTSTART", {}), ev["DTSTART"], tz)
                has_end = "DTEND" in ev
                if has_end:
                    e_date, e_time = _value_to_date("DTEND", ev["_p"].get("DTEND", {}), ev["DTEND"], tz)
                else:
                    e_date, e_time = s_date, s_time
            except ValueError:
                continue
            if s_time is None:
                if not has_end:
                    e_date = s_date + timedelta(days=1)          # all-day event with no end = one day
            elif e_time is not None and e_time != datetime.min.time():
                e_date = e_date + timedelta(days=1)              # a timed event covers every day it touches
            if e_date <= s_date:
                e_date = s_date + timedelta(days=1)
            uid = (ev.get("UID") or "").strip() or f"nouid-{s_date.isoformat()}"
            events.append({"uid": uid, "start": s_date.isoformat(), "end": e_date.isoformat(),
                           "summary": ical_event_details.unescape(ev.get("SUMMARY", "")),
                           "description": ical_event_details.unescape(ev.get("DESCRIPTION", ""))})
        elif current is not None and ":" in line:
            head, _, value = line.partition(":")
            parts = head.split(";")
            name = parts[0].strip().upper()
            params = {}
            for p in parts[1:]:
                k, _, v = p.partition("=")
                params[k.strip().upper()] = v.strip().strip('"')
            if name not in current:                 # first occurrence wins
                current[name] = value
                current["_p"][name] = params
    return events


# ─── Building ─────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold at 75 octets (RFC 5545), continuation lines start with one space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks, first = [], True
    while raw:
        limit = 75 if first else 74
        cut = limit
        while cut > 0 and (raw[cut:cut + 1] and (raw[cut] & 0xC0) == 0x80):
            cut -= 1                                  # never split a multibyte character
        chunks.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
        first = False
    return "\r\n ".join(chunks)


def build_ics(calendar_name: str, events: list[dict]) -> str:
    """events: [{uid, start, end, summary, modified(datetime)}] -- all-day."""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HAIP//Calendar sync//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(calendar_name)}"]
    for ev in events:
        s = ev["start"].replace("-", "")
        e = ev["end"].replace("-", "")
        mod = (ev.get("modified") or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{now}", f"LAST-MODIFIED:{mod}",
                  f"DTSTART;VALUE=DATE:{s}", f"DTEND;VALUE=DATE:{e}",
                  f"SUMMARY:{_esc(ev.get('summary') or 'Reserved')}", "TRANSP:OPAQUE", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def export_events(db: Session, feed) -> list[dict]:
    """What HAIP publishes for this link: bookings and blocks, no guest detail."""
    from app.models.ical_feed import ICalFeed
    from app.models.property import BlockedDate, Stay

    horizon = (date.today() - _EXPORT_PAST).isoformat()
    events: list[dict] = []

    for st in (
        db.query(Stay)
        .filter(Stay.tenant_id == feed.tenant_id, Stay.property_id == feed.property_id,
                Stay.status.in_(["confirmed", "checked_in"]), Stay.hostaway_booking_id.is_(None),
                Stay.check_out >= horizon)
        .all()
    ):
        end = st.check_out if st.check_out > st.check_in else st.check_in + timedelta(days=1)   # same-day stay
        events.append({"uid": f"stay-{st.id}{UID_SUFFIX}", "start": st.check_in.isoformat(), "end": end.isoformat(),
                       "summary": "Reserved", "modified": st.updated_at})

    other_ids = {
        f.id for f in db.query(ICalFeed).filter(
            ICalFeed.tenant_id == feed.tenant_id, ICalFeed.property_id == feed.property_id,
            ICalFeed.is_active.is_(True), ICalFeed.id != feed.id).all()
    }
    for b in (
        db.query(BlockedDate)
        .filter(BlockedDate.tenant_id == feed.tenant_id, BlockedDate.property_id == feed.property_id,
                BlockedDate.is_active.is_(True), BlockedDate.blocked_to >= horizon)
        .all()
    ):
        notes = b.notes or ""
        m = _FEED_ID_NOTE.match(notes)
        if m:
            if m.group(1) not in other_ids:          # this link's own import, or a removed link
                continue
        elif notes.startswith("ical:") or notes.startswith("rw_avail_"):
            continue                                 # PMS-derived: not ours to republish
        events.append({"uid": f"block-{b.id}{UID_SUFFIX}", "start": b.blocked_from, "end": b.blocked_to,
                       "summary": "Blocked", "modified": b.updated_at})
    events.sort(key=lambda e: (e["start"], e["uid"]))
    return events


# ─── Import ───────────────────────────────────────────────────────────────────

def fetch_ics(url: str) -> str:
    """Download a calendar. Goes through the SSRF guard: the URL is user-supplied."""
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    resp = safe_get(url, timeout=20, headers={"Accept": "text/calendar, text/plain, */*"})
    if resp.status_code != 200:
        raise ValueError(f"The calendar link answered with HTTP {resp.status_code}. Check that it is the right link and still active.")
    if len(resp.content) > _MAX_BYTES:
        raise ValueError("That calendar is unexpectedly large.")
    text = resp.text
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("That link didn't return a calendar (expected an .ics feed).")
    return text


def _tenant_tz(db: Session, tenant_id: str) -> ZoneInfo:
    from app.core.tenant_tz import get_tz
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    return get_tz(tenant) if tenant else ZoneInfo("Asia/Kolkata")


def _vehicle_rules(db: Session, feed) -> dict[str, list[str]]:
    """{property_id: keywords} for a shared calendar; empty = the link belongs to one property."""
    from app.models.ical_feed import ICalFeedVehicle
    rows = db.query(ICalFeedVehicle).filter_by(feed_id=feed.id, tenant_id=feed.tenant_id).all()
    return {r.property_id: [k for k in (r.keywords or []) if isinstance(k, str) and k.strip()] for r in rows}


def _save_details(db: Session, feed, block, ev: dict, details: dict, source: str, needs_vehicle: bool) -> None:
    from app.models.ical_feed import ICalEventDetail
    row = db.query(ICalEventDetail).filter_by(blocked_date_id=block.id).first()
    if row is None:
        row = ICalEventDetail(tenant_id=feed.tenant_id, blocked_date_id=block.id, feed_id=feed.id, event_uid=ev["uid"][:255])
        db.add(row)
    row.title = (ev.get("summary") or "")[:255] or None
    row.details = details
    row.dates_source = source
    row.needs_vehicle = needs_vehicle


def _ask_which_vehicle(db: Session, feed, ev: dict, start: str, end: str) -> None:
    """One task per event that named no vehicle, so someone says which caravan it is (shows on My Day)."""
    from app.models.task import Task
    title = f"Which vehicle? {(ev.get('summary') or 'Calendar booking')[:120]} ({start} to {end})"[:255]
    if db.query(Task.id).filter_by(tenant_id=feed.tenant_id, title=title, is_done=False).first():
        return
    db.add(Task(tenant_id=feed.tenant_id, title=title, priority="high", due_date=datetime.now(timezone.utc)))


def sync_feed(db: Session, feed, fetcher: Optional[Callable[[str], str]] = None) -> dict:
    """Read the link's calendar into BlockedDate rows. Never raises: the outcome
    is recorded on the feed (last_status / last_error) and returned.

    A link with vehicle keywords is a SHARED calendar: each event blocks the vehicles it names, or all of them when it
    names none (and a task asks which). The days blocked are the trip dates written in the description when those are
    sensible, else the event's own days. The event's title and the details read from its description are kept with the block."""
    from app.models.property import BlockedDate

    now = datetime.now(timezone.utc)
    if not feed.import_url_enc:
        return {"status": "skipped", "reason": "export only"}
    try:
        url = decrypt_credentials(feed.import_url_enc).get("url", "")
        if not url:
            raise ValueError("The saved calendar link could not be read. Please save it again.")
        tz = _tenant_tz(db, feed.tenant_id)
        events = parse_ics((fetcher or fetch_ics)(url), tz)
    except Exception as exc:  # noqa: BLE001
        feed.last_status, feed.last_error, feed.last_synced_at = "error", str(exc)[:500], now
        db.commit()
        log.warning("ical_sync_failed", feed_id=feed.id, error=str(exc)[:200])
        return {"status": "error", "error": str(exc)[:500]}

    today = datetime.now(tz).date()
    floor = (today - _PAST_WINDOW).isoformat()
    seen: dict[str, dict] = {}
    for ev in events:
        if ev["uid"].endswith(UID_SUFFIX):           # our own reservation coming back
            continue
        if ev["end"] <= floor:
            continue
        key = ev["uid"] if ev["uid"] not in seen else f"{ev['uid']}#{ev['start']}"
        seen[key] = ev

    rules = _vehicle_rules(db, feed)
    prefix = marker(feed.id)
    existing = {
        (b.property_id, (b.notes or "")[len(prefix):]): b
        for b in db.query(BlockedDate).filter(
            BlockedDate.tenant_id == feed.tenant_id, BlockedDate.notes.like(prefix + "%")).all()
    }
    wanted: set[tuple[str, str]] = set()
    properties_used: set[str] = set()
    added = changed = lifted = ambiguous = 0
    for key, ev in seen.items():
        details = ical_event_details.extract(ev.get("summary", ""), ev.get("description", ""))
        start, end, source = ical_event_details.block_window(ev["start"], ev["end"], details)
        if rules:
            hits = ical_event_details.match_vehicles(ev.get("summary", "") + "\n" + ev.get("description", ""), rules)
            needs_vehicle = not hits
            targets = hits or list(rules)
        else:
            needs_vehicle, targets = False, [feed.property_id]
        if needs_vehicle:
            ambiguous += 1
            if end > today.isoformat():
                _ask_which_vehicle(db, feed, ev, start, end)
        for property_id in targets:
            wanted.add((property_id, key))
            properties_used.add(property_id)
            row = existing.get((property_id, key))
            if row is None:
                row = BlockedDate(tenant_id=feed.tenant_id, property_id=property_id, blocked_from=start, blocked_to=end,
                                  reason=IMPORT_REASON, notes=prefix + key, is_active=True)
                db.add(row)
                db.flush()
                added += 1
            elif (row.blocked_from, row.blocked_to, row.is_active) != (start, end, True):
                row.blocked_from, row.blocked_to, row.is_active = start, end, True
                changed += 1
            _save_details(db, feed, row, ev, details, source, needs_vehicle)
    for (property_id, key), row in existing.items():
        # Gone from the source calendar (cancelled), or no longer meant for this vehicle: lifted. Past ones are history.
        if (property_id, key) not in wanted and row.is_active and row.blocked_to >= today.isoformat():
            row.is_active = False
            lifted += 1

    db.flush()
    conflicts = sum(_flag_double_bookings(db, feed, today, pid) for pid in (properties_used or {feed.property_id}))
    feed.last_status, feed.last_error, feed.last_synced_at = "ok", None, now
    feed.last_event_count, feed.last_conflicts = len(seen), conflicts
    db.commit()
    log.info("ical_sync_done", feed_id=feed.id, added=added, changed=changed, lifted=lifted, conflicts=conflicts, ambiguous=ambiguous)
    return {"status": "ok", "events": len(seen), "added": added, "changed": changed, "lifted": lifted, "conflicts": conflicts,
            "needs_vehicle": ambiguous}


def _flag_double_bookings(db: Session, feed, today: date, property_id: Optional[str] = None) -> int:
    """An imported reservation that overlaps a HAIP booking means two guests
    hold the same dates. Count them and raise a task so someone sorts it out
    (it shows on My Day) -- iCal sync has no way to stop it, only to notice.
    An event that named no vehicle already has its own "which vehicle?" task and is not counted here."""
    from app.models.ical_feed import ICalEventDetail
    from app.models.property import BlockedDate, Property, Stay
    from app.models.task import Task

    property_id = property_id or feed.property_id
    prop = db.query(Property).filter_by(id=property_id, tenant_id=feed.tenant_id).first()
    pname = prop.name if prop else "property"
    undecided = {r[0] for r in db.query(ICalEventDetail.blocked_date_id).filter_by(feed_id=feed.id, needs_vehicle=True).all()}
    blocks = [b for b in db.query(BlockedDate).filter(
        BlockedDate.tenant_id == feed.tenant_id, BlockedDate.property_id == property_id,
        BlockedDate.is_active.is_(True), BlockedDate.notes.like(marker(feed.id) + "%"),
        BlockedDate.blocked_to > today.isoformat()).all() if b.id not in undecided]
    count = 0
    for b in blocks:
        clashes = db.query(Stay).filter(
            Stay.tenant_id == feed.tenant_id, Stay.property_id == property_id,
            Stay.status.in_(["confirmed", "checked_in"]),
            Stay.check_in < b.blocked_to, Stay.check_out > b.blocked_from).all()
        for stay in clashes:
            count += 1
            title = f"Double booking on {pname}: {feed.name} {b.blocked_from} to {b.blocked_to}"[:255]
            if db.query(Task.id).filter_by(tenant_id=feed.tenant_id, guest_id=stay.guest_id, title=title, is_done=False).first():
                continue
            db.add(Task(tenant_id=feed.tenant_id, title=title, priority="high", guest_id=stay.guest_id,
                        inquiry_id=stay.inquiry_id, due_date=datetime.now(timezone.utc)))
            try:
                from app.services.push_service import send_to_tenant
                send_to_tenant(db, feed.tenant_id, title="Double booking",
                               body=f"{feed.name} has {pname} reserved {b.blocked_from} to {b.blocked_to}, which overlaps a HAIP booking.",
                               url="/dashboard/my-day")
            except Exception as exc:  # noqa: BLE001  -- push is best effort
                log.warning("ical_conflict_push_failed", error=str(exc))
    return count


def feed_cap() -> int:
    return _FEED_CAP_PER_PROPERTY


def tenant_for_export_token(db, token: str) -> Optional[str]:
    """Tenant that owns an active export token, or None. On Postgres this goes
    through the SECURITY DEFINER function (RLS hides ical_feeds until a tenant
    is set, and a public request has none); elsewhere a plain query."""
    from sqlalchemy import text
    from app.models.ical_feed import ICalFeed
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return db.execute(text("SELECT ical_feed_tenant(:t)"), {"t": token}).scalar()
    feed = db.query(ICalFeed).filter_by(export_token=token, is_active=True).first()
    return feed.tenant_id if feed else None
