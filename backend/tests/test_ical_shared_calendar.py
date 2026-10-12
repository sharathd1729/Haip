"""One shared Google Calendar for several vehicles (the Ratha team's setup).

Pinned here: an event blocks the vehicle(s) it names; an event that names none blocks all of them and raises ONE "which
vehicle?" task; correcting the title in Google moves the block on the next read; the days blocked come from the trip dates in
the description when sensible; the title and the booking details are kept and shown on the calendar, with amounts only for
roles that hold revenue.read; the keyword rules are validated and tenant-scoped; a link with no rules behaves exactly as before.
"""
import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.ical_feed import ICalEventDetail, ICalFeedVehicle
from app.models.property import BlockedDate
from app.models.task import Task
from app.models.user import User, UserRole
from app.services import ical_sync_service as svc
from tests.test_ical_feeds import _auth, _d, _feed, _ics, _prop, _tenant
from tests.conftest import seed_capabilities

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

START, END = "2030-03-20", "2030-03-21"          # a single all-day event on 20 March 2030


def _event(uid, summary, description="", start=START, end=END):
    esc = description.replace("\n", "\\n")
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART;VALUE=DATE:{start.replace('-', '')}\r\nDTEND;VALUE=DATE:{end.replace('-', '')}\r\n"
            f"SUMMARY:{summary}\r\nDESCRIPTION:{esc}\r\nEND:VEVENT\r\n")


NEHA = ("BOOKING\nGuest Name: Neha\nContact Number: +91 98456 00000\nDestination: Kabini\n"
        "Dates: 20th - 22nd March 2030, noon to ~6 PM\nGuests: 2 Adults + 1 Child\n"
        "Total Booking Amount: Rs 70,000\nAdvance Received: Rs 35,000\nBalance Amount: Rs 35,000")
# Without a phone number an event is not complete enough to become a booking, so it stays a calendar block.
NEHA_BLOCK = NEHA.replace("Contact Number: +91 98456 00000\n", "")
BOTH = "Guest Name: Krithika\nVehicles: 2 Caravans (White and Black)\nDates: 25th - 27th March 2030"


@pytest.fixture()
def shared(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    placeholder = _prop(db, tid, "Unassigned (legacy bookings)")
    white, black = _prop(db, tid, "Ratha White"), _prop(db, tid, "Ratha Black")
    feed = _feed(db, tid, placeholder.id, name="Google")
    db.add(ICalFeedVehicle(tenant_id=tid, feed_id=feed.id, property_id=white.id, keywords=["white", "white ratha"]))
    db.add(ICalFeedVehicle(tenant_id=tid, feed_id=feed.id, property_id=black.id, keywords=["black"]))
    db.commit()
    return {"tid": tid, "feed": feed, "placeholder": placeholder, "white": white, "black": black, "tu": tenant_and_user}


def _active(db, prop):
    return sorted((b.blocked_from, b.blocked_to) for b in db.query(BlockedDate).filter_by(property_id=prop.id, is_active=True).all())


def _sync(db, feed, *events):
    return svc.sync_feed(db, feed, fetcher=lambda u: _ics(*events))


def test_each_event_blocks_the_vehicle_it_names_and_nothing_else(db, shared):
    r = _sync(db, shared["feed"],
              _event("a@g", "Poornima| white ratha| Jishanth"),
              _event("b@g", "Shri personal/black Ratha", start="2030-04-01", end="2030-04-05"))
    assert r["status"] == "ok" and r["needs_vehicle"] == 0
    assert _active(db, shared["white"]) == [(START, END)]
    assert _active(db, shared["black"]) == [("2030-04-01", "2030-04-05")]
    assert _active(db, shared["placeholder"]) == []                       # the link's own (placeholder) property gets nothing


def test_an_event_naming_both_vehicles_blocks_both(db, shared):
    _sync(db, shared["feed"], _event("c@g", "Krithika| Jishanth", BOTH, start="2030-03-25", end="2030-03-26"))
    assert _active(db, shared["white"]) == _active(db, shared["black"]) == [("2030-03-25", "2030-03-27")]


def test_an_event_naming_no_vehicle_blocks_all_and_asks_once(db, shared):
    ev = _event("d@g", "Manisha| Jishanth", "Guest Name: Manisha")
    r = _sync(db, shared["feed"], ev)
    assert r["needs_vehicle"] == 1 and r["conflicts"] == 0
    assert _active(db, shared["white"]) == _active(db, shared["black"]) == [(START, END)]
    _sync(db, shared["feed"], ev)                                          # a second read does not ask again
    tasks = db.query(Task).filter(Task.tenant_id == shared["tid"], Task.title.like("Which vehicle?%")).all()
    assert len(tasks) == 1 and "Manisha" in tasks[0].title


def test_fixing_the_title_in_google_moves_the_block_on_the_next_read(db, shared):
    _sync(db, shared["feed"], _event("e@g", "Manisha| Jishanth"))
    assert _active(db, shared["white"]) and _active(db, shared["black"])
    r = _sync(db, shared["feed"], _event("e@g", "Manisha| black Ratha| Jishanth"))
    assert r["lifted"] == 1 and r["needs_vehicle"] == 0
    assert _active(db, shared["white"]) == [] and _active(db, shared["black"]) == [(START, END)]
    again = _sync(db, shared["feed"], _event("e@g", "Manisha| black Ratha| Jishanth"))
    assert (again["added"], again["changed"], again["lifted"]) == (0, 0, 0)    # nothing flaps


def test_the_blocked_days_follow_the_trip_dates_in_the_description(db, shared):
    _sync(db, shared["feed"], _event("f@g", "Neha| white ratha| Jishanth", NEHA_BLOCK))
    assert _active(db, shared["white"]) == [("2030-03-20", "2030-03-22")]      # event is one day; the trip is two nights
    detail = db.query(ICalEventDetail).filter_by(feed_id=shared["feed"].id).one()
    assert detail.dates_source == "description" and detail.needs_vehicle is False
    assert detail.title == "Neha| white ratha| Jishanth"
    assert detail.details["guest_name"] == "Neha"
    assert detail.details["amounts"]["total"] == 70000.0 and detail.details["amounts"]["balance"] == 35000.0


def test_a_trip_date_far_from_the_event_is_ignored(db, shared):
    _sync(db, shared["feed"], _event("g@g", "white ratha trip", "Dates: 2nd - 4th January 2031"))
    assert _active(db, shared["white"]) == [(START, END)]
    assert db.query(ICalEventDetail).filter_by(feed_id=shared["feed"].id).one().dates_source == "event"


def test_a_link_with_no_vehicle_rules_still_blocks_its_own_property(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid, "Caravan 1")
    feed = _feed(db, tid, prop.id, name="Airbnb")
    r = _sync(db, feed, _event("h@a", "Reserved"))
    assert r["added"] == 1 and r["needs_vehicle"] == 0 and _active(db, prop) == [(START, END)]


# ── endpoints ────────────────────────────────────────────────────────────────

def test_saving_vehicle_rules_reads_the_calendar_and_lists_what_still_needs_a_vehicle(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    placeholder, white, black = _prop(db, tid, "Unassigned"), _prop(db, tid, "Ratha White"), _prop(db, tid, "Ratha Black")
    feed = _feed(db, tid, placeholder.id, name="Google")
    db.commit()
    body = {"vehicles": {white.id: [" white ", "White", "white ratha"], black.id: ["black"]}}
    with patch.object(svc, "fetch_ics", lambda u: _ics(_event("i@g", "Poornima| white ratha"), _event("j@g", "Manisha| Jishanth"))):
        r = client.patch(f"/api/v1/ical-feeds/{feed.id}", json=body, headers=_auth(tenant_and_user))
    assert r.status_code == 200, r.text
    out = r.json()
    assert {v["property_name"]: v["keywords"] for v in out["vehicles"]} == {"Ratha White": ["white", "white ratha"], "Ratha Black": ["black"]}
    assert out["needs_vehicle"] == 1 and out["sync"]["status"] == "ok"
    listed = client.get("/api/v1/ical-feeds", headers=_auth(tenant_and_user)).json()
    assert listed[0]["needs_vehicle"] == 1 and len(listed[0]["vehicles"]) == 2
    cleared = client.patch(f"/api/v1/ical-feeds/{feed.id}", json={"vehicles": {}}, headers=_auth(tenant_and_user)).json()
    assert cleared["vehicles"] == []


def test_vehicle_rules_are_validated_and_tenant_scoped(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid, "Mine")
    feed = _feed(db, tid, prop.id)
    other = _prop(db, _tenant(db), "Not mine")
    db.commit()
    h = _auth(tenant_and_user)
    assert client.patch(f"/api/v1/ical-feeds/{feed.id}", json={"vehicles": {other.id: ["x"]}}, headers=h).status_code == 404
    assert client.patch(f"/api/v1/ical-feeds/{feed.id}", json={"vehicles": {prop.id: ["  "]}}, headers=h).status_code == 422
    assert client.patch(f"/api/v1/ical-feeds/{feed.id}", json={"vehicles": {prop.id: [f"k{i}" for i in range(11)]}}, headers=h).status_code == 422


def test_deleting_the_link_removes_its_rules_and_event_details(client, db, shared):
    _sync(db, shared["feed"], _event("k@g", "white ratha"))
    assert db.query(ICalEventDetail).count() >= 1
    r = client.delete(f"/api/v1/ical-feeds/{shared['feed'].id}", headers=_auth(shared["tu"]))
    assert r.status_code == 204
    assert db.query(ICalFeedVehicle).filter_by(feed_id=shared["feed"].id).count() == 0
    assert db.query(ICalEventDetail).filter_by(feed_id=shared["feed"].id).count() == 0


# ── the calendar shows the details, money only with revenue.read ─────────────

def _calendar(client, headers):
    return client.get("/api/v1/calendar", params={"from_date": "2030-03-18", "to_date": "2030-03-30"}, headers=headers)


def test_the_calendar_carries_the_event_details_and_withholds_amounts_without_revenue_read(client, db, shared):
    _sync(db, shared["feed"], _event("l@g", "Neha| white ratha| Jishanth", NEHA_BLOCK))
    owner = _calendar(client, _auth(shared["tu"])).json()
    white = next(r for r in owner["properties"] if r["property_id"] == shared["white"].id)
    event = next(b for b in white["blocks"] if b["event"])["event"]
    assert event["title"] == "Neha| white ratha| Jishanth" and event["details"]["guest_name"] == "Neha"
    assert event["details"]["amounts"]["total"] == 70000.0 and event["dates_source"] == "description"

    reservations = User(id=str(uuid.uuid4()), tenant_id=shared["tid"], name="Res", email=f"r-{uuid.uuid4().hex[:5]}@t.com",
                        hashed_password=get_password_hash("pw"), role=UserRole.RESERVATIONS, is_active=True)
    db.add(reservations)
    db.commit()
    headers = {"Authorization": "Bearer " + create_access_token({"sub": reservations.id, "tenant_id": shared["tid"], "role": "reservations"})}
    res = _calendar(client, headers)
    assert res.status_code == 200
    w = next(r for r in res.json()["properties"] if r["property_id"] == shared["white"].id)
    shown = next(b for b in w["blocks"] if b["event"])["event"]
    assert shown["details"]["guest_name"] == "Neha" and "amounts" not in shown["details"]
    assert "70000" not in res.text and "35000" not in res.text


def test_another_workspace_never_sees_these_events(client, db, shared):
    _sync(db, shared["feed"], _event("m@g", "Neha| white ratha", NEHA_BLOCK))
    other = _tenant(db)
    seed_capabilities(db, other)
    owner = User(id=str(uuid.uuid4()), tenant_id=other, name="O", email=f"o-{uuid.uuid4().hex[:5]}@t.com",
                 hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True)
    db.add(owner)
    db.commit()
    h = {"Authorization": "Bearer " + create_access_token({"sub": owner.id, "tenant_id": other, "role": "owner"})}
    assert "Neha" not in _calendar(client, h).text
