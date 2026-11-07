"""Imported calendar holds as the Calendar and the Bookings strip show them, and "Hold only this villa".

A shared Google Calendar event that names no unit (villa / vehicle) is held on EVERY unit of that calendar: one BlockedDate per
unit, all with the same note ``ical:<feed id>:<event key>``. ``event_info`` describes each hold once for the screens (title
without bold markers, the calendar link's name, a key shared by every copy of the event, and whether it is waiting for a unit),
so they can show it once in a "Which villa?" row instead of on every unit.

``assign`` is a person's answer: the event is for this unit. It is stored (ICalEventAssignment, read by the sync as if the event
had named the unit), the other units' copies are lifted at once, and the "Which vehicle?" task is closed. Audited.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.ical_feed import ICalEventAssignment, ICalEventDetail, ICalFeed
from app.models.property import BlockedDate, Property
from app.services import ical_event_details, ical_sync_service


class HoldError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _key(block: BlockedDate, feed_id: str) -> str:
    return (block.notes or "")[len(ical_sync_service.marker(feed_id)) :]


def event_info(db: Session, tenant_id: str, blocks: list[BlockedDate], can_revenue: bool) -> dict[str, dict]:
    """{block id: {title, details, dates_source, needs_vehicle, event_key, feed_name}} for blocks imported from a calendar.
    One query per kind; amounts only with revenue.read. Never raises: a failure returns {} and the screens show plain holds."""
    try:
        ids = [b.id for b in blocks]
        if not ids:
            return {}
        rows = (
            db.query(ICalEventDetail)
            .filter(ICalEventDetail.tenant_id == tenant_id, ICalEventDetail.blocked_date_id.in_(ids))
            .all()
        )
        feeds = (
            dict(
                db.query(ICalFeed.id, ICalFeed.name)
                .filter(ICalFeed.tenant_id == tenant_id, ICalFeed.id.in_({d.feed_id for d in rows}))
                .all()
            )
            if rows
            else {}
        )
        by_id = {b.id: b for b in blocks}
        out = {}
        for d in rows:
            shown = dict(d.details or {})
            if not can_revenue:
                shown.pop("amounts", None)  # booking money needs revenue.read, like per-stay amounts
            if isinstance(shown.get("guest_name"), str):
                shown["guest_name"] = ical_event_details.clean_name(shown["guest_name"])
            out[d.blocked_date_id] = {
                "title": ical_event_details.clean_name(d.title or "") or None,
                "details": shown,
                "dates_source": d.dates_source,
                "needs_vehicle": bool(d.needs_vehicle),
                "event_key": f"{d.feed_id}:{_key(by_id[d.blocked_date_id], d.feed_id)}",
                "feed_name": feeds.get(d.feed_id),
            }
        return out
    except Exception:  # noqa: BLE001
        return {}


def _waiting(db: Session, tenant_id: str, block_id: str) -> tuple[BlockedDate, ICalEventDetail, ICalFeed, str]:
    block = db.query(BlockedDate).filter_by(id=block_id, tenant_id=tenant_id).first()
    detail = (
        db.query(ICalEventDetail).filter_by(blocked_date_id=block_id, tenant_id=tenant_id).first() if block else None
    )
    if block is None or detail is None:
        raise HoldError(404, "This calendar hold is no longer there. Refresh the calendar.")
    feed = db.query(ICalFeed).filter_by(id=detail.feed_id, tenant_id=tenant_id).first()
    if feed is None:
        raise HoldError(404, "The calendar link this hold came from was removed.")
    return block, detail, feed, _key(block, feed.id)


def options(db: Session, tenant_id: str, block_id: str) -> dict:
    """The units of this hold's shared calendar, each with ``free`` = no booking or other hold on the dates (this event's own
    copies do not count)."""
    from app.services import booking_service as bsvc

    block, detail, feed, key = _waiting(db, tenant_id, block_id)
    unit_ids = list(ical_sync_service._vehicle_rules(db, feed))
    names = (
        dict(
            db.query(Property.id, Property.name)
            .filter(Property.tenant_id == tenant_id, Property.id.in_(unit_ids))
            .all()
        )
        if unit_ids
        else {}
    )
    start, end = date.fromisoformat(block.blocked_from), date.fromisoformat(block.blocked_to)
    found = {pid: bsvc.find_conflicts(db, tenant_id, pid, start, end, ignore_unassigned=True) for pid in names}
    # Holds still waiting for their unit (this event's copies, and other "Which villa?" events) are not real: they never
    # make a unit look busy, or two unplaced events on the same dates would leave nothing to pick.
    block_ids = {c["id"] for cs in found.values() for c in cs if c.get("type") == "block"}
    waiting = (
        {
            i
            for (i,) in db.query(ICalEventDetail.blocked_date_id)
            .filter(
                ICalEventDetail.tenant_id == tenant_id,
                ICalEventDetail.blocked_date_id.in_(block_ids),
                ICalEventDetail.needs_vehicle.is_(True),
            )
            .all()
        }
        if block_ids
        else set()
    )
    units = []
    for pid in sorted(names, key=lambda i: names[i].lower()):
        clashes = [c for c in found[pid] if not (c.get("type") == "block" and c["id"] in waiting)]
        units.append({"property_id": pid, "name": names[pid], "free": not clashes})
    return {
        "block_id": block.id,
        "needs_unit": bool(detail.needs_vehicle),
        "from": block.blocked_from,
        "to": block.blocked_to,
        "units": units,
    }


def assign(db: Session, tenant_id: str, block_id: str, property_id: str, user_id: str | None) -> dict:
    """Hold the event on ``property_id`` only. Raises HoldError (404 / 409 / 422) in plain words. The caller commits."""
    from app.models.task import Task

    block, detail, feed, key = _waiting(db, tenant_id, block_id)
    if not detail.needs_vehicle:
        raise HoldError(409, "This calendar event already names its unit.")
    choice = next((u for u in options(db, tenant_id, block_id)["units"] if u["property_id"] == property_id), None)
    if choice is None:
        raise HoldError(422, "Pick one of the units of this calendar.")
    if not choice["free"]:
        raise HoldError(409, f"{choice['name']} is not free on these dates. Pick another one.")
    row = db.query(ICalEventAssignment).filter_by(tenant_id=tenant_id, feed_id=feed.id, event_key=key[:300]).first()
    if row is None:
        db.add(
            ICalEventAssignment(
                tenant_id=tenant_id, feed_id=feed.id, event_key=key[:300], property_id=property_id, assigned_by=user_id
            )
        )
    else:
        row.property_id, row.assigned_by = property_id, user_id
    note = ical_sync_service.marker(feed.id) + key
    copies = db.query(BlockedDate).filter(BlockedDate.tenant_id == tenant_id, BlockedDate.notes == note).all()
    lifted = 0
    for b in copies:
        keep = b.property_id == property_id
        if b.is_active != keep:
            lifted += 0 if keep else 1
            b.is_active = keep
    for d in (
        db.query(ICalEventDetail)
        .filter(ICalEventDetail.tenant_id == tenant_id, ICalEventDetail.blocked_date_id.in_([b.id for b in copies]))
        .all()
    ):
        d.needs_vehicle = False
    # The sync's own "Which vehicle?" task for this event (same title it wrote: ical_sync_service._ask_which_vehicle).
    title = f"Which vehicle? {(detail.title or 'Calendar booking')[:120]} ({block.blocked_from} to {block.blocked_to})"[
        :255
    ]
    closed = 0
    for t in db.query(Task).filter_by(tenant_id=tenant_id, title=title, is_done=False).all():
        t.is_done = True
        closed += 1
    append_audit(
        db,
        tenant_id=tenant_id,
        action="calendar.hold_assigned",
        actor_user_id=user_id,
        target_type="blocked_date",
        target_id=block.id,
        payload={"feed_id": feed.id, "property_id": property_id, "copies_lifted": lifted, "tasks_closed": closed},
    )
    return {"property_id": property_id, "name": choice["name"], "copies_lifted": lifted, "tasks_closed": closed}
