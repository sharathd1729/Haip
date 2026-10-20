"""Calendar clash tasks: an imported calendar reservation that overlaps a live HAIP booking on the same vehicle.

ONE open task per clash, a clash being (imported calendar block x vehicle). Its title is built by ``clash_title`` and is the
task's identity: "Double booking on <vehicle>: <calendar link> <from> to <to>". The same check that raises the task (the
calendar sync, ``ical_sync_service._flag_double_bookings``) closes it again: ``close_stale`` marks done every open clash task
whose title is not a clash that exists right now (the block was lifted or moved, the booking was cancelled or moved, the
vehicle was renamed, or the link was removed), with an audit row saying why. ``scripts/close_stale_clash_tasks.py`` runs the
same ``stale_tasks`` check by hand.

Tasks the calendar sync raises (clash, "Which vehicle?", "Not enough vehicles") carry no ``created_by``; My day lists them
as their own kind, ``clash`` ("Calendar clashes"), never as a lead follow-up (``is_calendar_task``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

CLASH_PREFIX = "Double booking on "
WHICH_VEHICLE_PREFIX = "Which vehicle? "
OVER_CAPACITY_PREFIX = "Not enough vehicles from "
CALENDAR_TASK_PREFIXES = (CLASH_PREFIX, WHICH_VEHICLE_PREFIX, OVER_CAPACITY_PREFIX)
LIVE = ("confirmed", "checked_in")
_FEED_ID_NOTE = re.compile(r"^ical:([0-9a-f-]{36}):")
_DATES = re.compile(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})")
_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class Clash:
    title: str
    feed_id: str
    feed_name: str
    property_id: str
    property_name: str
    block_id: str
    start: str
    end: str
    stays: list = field(default_factory=list)


def clash_title(property_name: str, feed_name: str, start: str, end: str) -> str:
    return f"{CLASH_PREFIX}{property_name}: {feed_name} {start} to {end}"[:255]


def is_calendar_task(task) -> bool:
    """Raised by the calendar sync, not by a person."""
    return task.created_by is None and (task.title or "").startswith(CALENDAR_TASK_PREFIXES)


def calendar_task_sql():
    """SQL twin of ``is_calendar_task``."""
    from sqlalchemy import and_, or_
    from app.models.task import Task
    return and_(Task.created_by.is_(None), or_(*[Task.title.like(p + "%") for p in CALENDAR_TASK_PREFIXES]))


def describe(title: str, properties: dict[str, str]) -> dict:
    """{start, end, property_id, vehicle} read back from a calendar task title (any may be None). ``properties`` = {id: name}."""
    out = {"start": None, "end": None, "property_id": None, "vehicle": None}
    m = _DATES.search(title or "")
    if m:
        out["start"], out["end"] = m.group(1), m.group(2)
    elif (title or "").startswith(OVER_CAPACITY_PREFIX):
        d = _DAY.search(title)
        out["start"] = d.group(1) if d else None
    if (title or "").startswith(CLASH_PREFIX):
        # Longest name first, so "Ratha 10" is not read as "Ratha 1".
        for pid, name in sorted(properties.items(), key=lambda kv: -len(kv[1] or "")):
            if name and title.startswith(f"{CLASH_PREFIX}{name}: "):
                out["property_id"], out["vehicle"] = pid, name
                break
    return out


def current_clashes(db: Session, tenant_id: str, today: date, *, feed_id: Optional[str] = None,
                    property_ids: Optional[list[str]] = None) -> list[Clash]:
    """Every clash that exists now: an active imported block (still ahead of us, its vehicle decided) that overlaps a
    confirmed or checked-in booking on the same vehicle. A handful of queries for the whole workspace, none per block."""
    from app.models.ical_feed import ICalEventDetail, ICalFeed
    from app.models.property import BlockedDate, Property, Stay

    fq = db.query(ICalFeed).filter(ICalFeed.tenant_id == tenant_id)
    fq = fq.filter(ICalFeed.id == feed_id) if feed_id else fq.filter(ICalFeed.is_active.is_(True))
    feeds = {f.id: f for f in fq.all()}
    if not feeds:
        return []
    bq = db.query(BlockedDate).filter(
        BlockedDate.tenant_id == tenant_id, BlockedDate.is_active.is_(True), BlockedDate.blocked_to > today.isoformat(),
        BlockedDate.notes.like(f"ical:{feed_id}:%" if feed_id else "ical:%"))
    if property_ids is not None:
        bq = bq.filter(BlockedDate.property_id.in_(list(property_ids) or [""]))
    blocks = []
    for b in bq.all():
        m = _FEED_ID_NOTE.match(b.notes or "")
        if m and m.group(1) in feeds:
            blocks.append((b, feeds[m.group(1)]))
    if not blocks:
        return []
    undecided = {r[0] for r in db.query(ICalEventDetail.blocked_date_id).filter(
        ICalEventDetail.tenant_id == tenant_id, ICalEventDetail.needs_vehicle.is_(True),
        ICalEventDetail.blocked_date_id.in_([b.id for b, _ in blocks])).all()}
    blocks = [(b, f) for b, f in blocks if b.id not in undecided]
    prop_ids = list({b.property_id for b, _ in blocks})
    if not prop_ids:
        return []
    names = {p.id: p.name for p in db.query(Property.id, Property.name).filter(
        Property.tenant_id == tenant_id, Property.id.in_(prop_ids)).all()}
    earliest = min(b.blocked_from for b, _ in blocks)
    stays_by_prop: dict[str, list] = {}
    for s in (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id.in_(prop_ids), Stay.status.in_(LIVE),
                                    Stay.check_out > earliest).order_by(Stay.check_in.asc(), Stay.id.asc()).all()):
        stays_by_prop.setdefault(s.property_id, []).append(s)
    out = []
    for b, f in sorted(blocks, key=lambda bf: (bf[0].blocked_from, bf[0].id)):
        hits = [s for s in stays_by_prop.get(b.property_id, [])
                if str(s.check_in)[:10] < b.blocked_to and str(s.check_out)[:10] > b.blocked_from]
        if hits:
            pname = names.get(b.property_id) or "property"
            out.append(Clash(clash_title(pname, f.name, b.blocked_from, b.blocked_to), f.id, f.name, b.property_id, pname,
                             b.id, b.blocked_from, b.blocked_to, hits))
    return out


def _why(db: Session, tenant_id: str, title: str, today: date) -> str:
    """Plain words for why a clash task is no longer a clash (for the audit row and the script's report)."""
    from app.models.ical_feed import ICalFeed
    from app.models.property import Property
    props = {p.id: p.name for p in db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id).all()}
    info = describe(title, props)
    if info["property_id"] is None:
        return "the vehicle it names no longer exists under that name"
    rest = title[len(f"{CLASH_PREFIX}{info['vehicle']}: "):]
    feeds = [f for f in db.query(ICalFeed).filter(ICalFeed.tenant_id == tenant_id, ICalFeed.is_active.is_(True)).all()
             if rest.startswith(f"{f.name} ")]
    if not feeds:
        return "the calendar link it names is no longer active"
    if info["end"] and info["end"] <= today.isoformat():
        return "the clash dates have passed"
    if not any(c.property_id == info["property_id"] and c.start == info["start"] and c.end == info["end"]
               for f in feeds for c in _blocks_only(db, tenant_id, today, f.id, info["property_id"])):
        return "the calendar block is gone (lifted, moved, or its vehicle is undecided)"
    return "no confirmed booking overlaps those dates on that vehicle any more"


def _blocks_only(db: Session, tenant_id: str, today: date, feed_id: str, property_id: str) -> list[Clash]:
    """The live blocks of one link on one vehicle, as clash-shaped rows (stays not required): used only to explain a close."""
    from app.models.property import BlockedDate
    rows = db.query(BlockedDate).filter(
        BlockedDate.tenant_id == tenant_id, BlockedDate.property_id == property_id, BlockedDate.is_active.is_(True),
        BlockedDate.blocked_to > today.isoformat(), BlockedDate.notes.like(f"ical:{feed_id}:%")).all()
    return [Clash("", feed_id, "", property_id, "", b.id, b.blocked_from, b.blocked_to) for b in rows]


def stale_tasks(db: Session, tenant_id: str, today: date) -> list[tuple]:
    """[(task, reason)] for every open clash task whose clash no longer exists, plus the extra copies of a clash that still
    exists (older syncs raised one task per overlapping booking; the oldest copy is kept)."""
    from app.models.task import Task
    live = {c.title for c in current_clashes(db, tenant_id, today)}
    rows = (db.query(Task).filter(Task.tenant_id == tenant_id, Task.is_done.is_(False), Task.created_by.is_(None),
                                  Task.title.like(CLASH_PREFIX + "%"))
            .order_by(Task.created_at.asc(), Task.id.asc()).all())
    out, kept = [], {}
    for t in rows:
        if t.title not in live:
            out.append((t, _why(db, tenant_id, t.title, today)))
        elif t.title in kept:
            out.append((t, f"duplicate of task {kept[t.title]} for the same clash"))
        else:
            kept[t.title] = t.id
    return out


def close_stale(db: Session, tenant_id: str, today: date, *, actor: str = "ical_sync") -> int:
    """Mark done every open clash task whose clash is gone, one audit row each. Does not commit (the caller does)."""
    from app.core.audit import append_audit
    stale = stale_tasks(db, tenant_id, today)
    now = datetime.now(timezone.utc)
    for task, reason in stale:
        task.is_done, task.completed_at = True, now
        append_audit(db, tenant_id=tenant_id, action="task.auto_closed", target_type="task", target_id=task.id,
                     payload={"actor": actor, "title": task.title, "reason": reason})
    return len(stale)
