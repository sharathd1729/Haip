"""'Which villa?' holds on a shared calendar, and how the Calendar counts calendar holds (services/calendar_holds.py).

Pinned here: an event that names no unit is described once (same event key on every copy, title without bold markers, the
link's name); "Hold only this unit" keeps it on the chosen unit, frees the others now AND on every later sync, closes the
"Which vehicle?" task and is audited; a unit with a booking on the dates is refused; other "Which villa?" holds never make a
unit look busy; wrong role = 403, another tenant = 404; the Calendar counts nights held by an event that names its unit
(apart from booked nights) and never counts the waiting ones.
"""

import uuid

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.ical_feed import ICalEventAssignment, ICalEventDetail, ICalFeedVehicle
from app.models.property import BlockedDate, Stay
from app.models.task import Task
from app.models.user import User, UserRole
from tests.conftest import seed_capabilities
from tests.test_ical_feeds import _auth, _feed, _prop, _tenant
from tests.test_ical_shared_calendar import END, START, _active, _event, _sync

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


@pytest.fixture()
def shared(db, tenant_and_user):
    """Two units on one shared calendar (as in test_ical_shared_calendar), plus the placeholder the link belongs to."""
    tid = tenant_and_user["tenant"].id
    placeholder = _prop(db, tid, "Unassigned (legacy bookings)")
    white, black = _prop(db, tid, "Ratha White"), _prop(db, tid, "Ratha Black")
    feed = _feed(db, tid, placeholder.id, name="Google")
    db.add(ICalFeedVehicle(tenant_id=tid, feed_id=feed.id, property_id=white.id, keywords=["white", "white ratha"]))
    db.add(ICalFeedVehicle(tenant_id=tid, feed_id=feed.id, property_id=black.id, keywords=["black"]))
    db.commit()
    return {"tid": tid, "feed": feed, "placeholder": placeholder, "white": white, "black": black, "tu": tenant_and_user}


WAITING = "Guest Name: *Mr.Saksham*"  # no phone: stays a block; names no vehicle: held on both


def _copy(db, shared, prop):
    return db.query(BlockedDate).filter_by(property_id=prop.id, tenant_id=shared["tid"]).one()


def _user(db, tid, role):
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("pw"),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": role.value})}


def test_a_waiting_event_is_described_once_and_listed_with_free_units(client, db, shared):
    _sync(db, shared["feed"], _event("w@g", "*Mag/Sharma*", WAITING))
    white = _copy(db, shared, shared["white"])
    res = client.get(
        "/api/v1/calendar", params={"from_date": "2030-03-18", "to_date": "2030-03-30"}, headers=_auth(shared["tu"])
    )
    events = [b["event"] for r in res.json()["properties"] for b in r["blocks"] if b["event"]]
    assert len(events) == 2 and len({e["event_key"] for e in events}) == 1  # one event, held on both units
    assert events[0]["title"] == "Mag/Sharma" and events[0]["details"]["guest_name"] == "Mr.Saksham"
    assert events[0]["needs_vehicle"] is True and events[0]["feed_name"] == "Google"
    assert res.json()["stats"]["waiting_events"] == 1 and res.json()["stats"]["held_nights"] == 0

    opts = client.get(f"/api/v1/ical-feeds/holds/{white.id}/options", headers=_auth(shared["tu"])).json()
    assert [u["name"] for u in opts["units"]] == ["Ratha Black", "Ratha White"]
    assert all(u["free"] for u in opts["units"])  # its own copies never count as busy


def test_hold_only_this_unit_frees_the_others_now_and_after_the_next_sync(client, db, shared):
    ev = _event("w@g", "Mag/Sharma", WAITING)
    _sync(db, shared["feed"], ev)
    task = (
        db.query(Task)
        .filter(Task.tenant_id == shared["tid"], Task.title.like("Which vehicle?%"), Task.is_done.is_(False))
        .one()
    )
    white = _copy(db, shared, shared["white"])
    res = client.post(
        f"/api/v1/ical-feeds/holds/{white.id}/assign",
        json={"property_id": shared["black"].id},
        headers=_auth(shared["tu"]),
    )
    assert res.status_code == 200 and res.json()["copies_lifted"] == 1 and res.json()["tasks_closed"] == 1
    db.expire_all()
    assert _active(db, shared["black"]) == [(START, END)] and _active(db, shared["white"]) == []
    assert db.get(Task, task.id).is_done is True
    assert db.query(AuditEvent).filter_by(tenant_id=shared["tid"], action="calendar.hold_assigned").count() == 1

    r = _sync(db, shared["feed"], ev)  # Google still names no unit
    assert r["needs_vehicle"] == 0
    assert _active(db, shared["black"]) == [(START, END)] and _active(db, shared["white"]) == []
    assert not db.query(ICalEventDetail).filter_by(tenant_id=shared["tid"], needs_vehicle=True).count()
    again = client.post(
        f"/api/v1/ical-feeds/holds/{white.id}/assign",
        json={"property_id": shared["white"].id},
        headers=_auth(shared["tu"]),
    )
    assert again.status_code == 409  # already placed


def test_a_unit_with_a_booking_on_the_dates_is_refused(client, db, shared):
    _sync(db, shared["feed"], _event("w@g", "Mag/Sharma", WAITING))
    g = Guest(id=str(uuid.uuid4()), tenant_id=shared["tid"], name="Asha", phone="+919800001111")
    db.add(g)
    db.add(
        Stay(
            tenant_id=shared["tid"],
            guest_id=g.id,
            property_id=shared["white"].id,
            check_in=_d0(),
            check_out=_d1(),
            status="confirmed",
            currency="INR",
            special_requests=[],
            channel_source="direct",
        )
    )
    db.commit()
    white = _copy(db, shared, shared["white"])
    opts = client.get(f"/api/v1/ical-feeds/holds/{white.id}/options", headers=_auth(shared["tu"])).json()
    assert {u["name"]: u["free"] for u in opts["units"]} == {"Ratha Black": True, "Ratha White": False}
    res = client.post(
        f"/api/v1/ical-feeds/holds/{white.id}/assign",
        json={"property_id": shared["white"].id},
        headers=_auth(shared["tu"]),
    )
    assert res.status_code == 409 and "not free" in res.json()["detail"]
    assert not db.query(ICalEventAssignment).filter_by(tenant_id=shared["tid"]).count()


def test_another_waiting_event_on_the_same_dates_does_not_make_units_busy(client, db, shared):
    _sync(db, shared["feed"], _event("w@g", "Mag/Sharma", WAITING), _event("x@g", "Iyer offsite", "Guest Name: Iyer"))
    white = db.query(BlockedDate).filter_by(property_id=shared["white"].id, tenant_id=shared["tid"]).first()
    opts = client.get(f"/api/v1/ical-feeds/holds/{white.id}/options", headers=_auth(shared["tu"])).json()
    assert all(u["free"] for u in opts["units"])


def test_wrong_role_and_other_tenant_cannot_place_a_hold(client, db, shared):
    _sync(db, shared["feed"], _event("w@g", "Mag/Sharma", WAITING))
    white = _copy(db, shared, shared["white"])
    body = {"property_id": shared["black"].id}
    foh = _user(db, shared["tid"], UserRole.FOH)
    assert client.post(f"/api/v1/ical-feeds/holds/{white.id}/assign", json=body, headers=foh).status_code == 403
    other = _tenant(db)
    seed_capabilities(db, other)
    owner = _user(db, other, UserRole.OWNER)
    assert client.get(f"/api/v1/ical-feeds/holds/{white.id}/options", headers=owner).status_code == 404
    assert client.post(f"/api/v1/ical-feeds/holds/{white.id}/assign", json=body, headers=owner).status_code == 404
    db.expire_all()
    assert _active(db, shared["white"]) == [(START, END)]  # nothing changed


def test_the_calendar_counts_named_calendar_holds_apart_from_bookings(client, db, shared):
    _sync(
        db,
        shared["feed"],
        _event("n@g", "Kapoor| white ratha", "Guest Name: Kapoor", start="2030-03-20", end="2030-03-23"),
    )
    res = client.get(
        "/api/v1/calendar", params={"from_date": "2030-03-18", "to_date": "2030-03-28"}, headers=_auth(shared["tu"])
    )
    stats = res.json()["stats"]
    rows = {r["property_name"]: r for r in res.json()["properties"]}
    assert rows["Ratha White"]["held_nights"] == 3 and rows["Ratha White"]["booked_nights"] == 0
    assert stats["held_nights"] == 3 and stats["booked_nights"] == 0 and stats["waiting_events"] == 0
    assert stats["possible_nights"] == 10 * len(rows)
    assert stats["occupancy_with_holds_pct"] == round(3 / stats["possible_nights"] * 100, 1)


def _d0():
    from datetime import date

    return date.fromisoformat(START)


def _d1():
    from datetime import date

    return date.fromisoformat(END)
