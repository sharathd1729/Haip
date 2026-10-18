"""caravan_availability: one answer to "is a caravan free from D1 to D2, which one, and what are the nearest free dates?".

It must count exactly what bookings and the calendar count (booking_service.find_conflicts): confirmed / checked-in stays (a
cancelled one frees the dates), every calendar block (maintenance, an iCal / Google Calendar import, personal), bookings with no
vehicle yet on a shared calendar, noon-to-noon back-to-back trips, the "Unassigned" placeholder never offered; and never another
tenant's data.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.models.guest import Guest
from app.models.ical_feed import ICalFeed, ICalFeedVehicle
from app.models.property import BlockedDate, Property, Stay
from app.models.tenant import Tenant
from app.services import caravan_availability as ca
from app.services import package_pricing_service as pps

TODAY = date.today()
D1 = TODAY + timedelta(days=30)
D2 = D1 + timedelta(days=2)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"ca-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _vehicle(db, t, name, max_adults=8):
    p = Property(id=str(uuid.uuid4()), tenant_id=t.id, name=name, slug=f"v-{uuid.uuid4().hex[:6]}", type="caravan",
                 max_adults=max_adults, is_active=True)
    db.add(p)
    db.commit()
    return p


def _stay(db, t, prop, ci, co, status="confirmed"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Other", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, property_id=prop.id, check_in=ci, check_out=co, status=status))
    db.commit()


def _block(db, t, prop, ci, co, reason="maintenance"):
    db.add(BlockedDate(id=str(uuid.uuid4()), tenant_id=t.id, property_id=prop.id, blocked_from=ci.isoformat(), blocked_to=co.isoformat(),
                       reason=reason, is_active=True))
    db.commit()


@pytest.fixture()
def fleet(db):
    t = _tenant(db)
    r1, r2 = _vehicle(db, t, "Ratha 1"), _vehicle(db, t, "Ratha 2")
    return t, r1, r2


def test_both_free_gives_the_first_vehicle_by_name(db, fleet):
    t, r1, _ = fleet
    out = ca.check(db, t.id, D1, D2, adults=4)
    assert out["available"] and out["vehicle"] == {"id": r1.id, "name": "Ratha 1"} and out["nights"] == 2
    assert out["window"] == "noon to noon" and out["alternatives"] == []


def test_an_overlapping_booking_moves_the_trip_to_the_other_vehicle(db, fleet):
    t, r1, r2 = fleet
    _stay(db, t, r1, D1 - timedelta(days=1), D1 + timedelta(days=1))
    out = ca.check(db, t.id, D1, D2, adults=4)
    assert out["available"] and out["vehicle"]["id"] == r2.id
    assert [(v["property_name"], v["status"]) for v in out["vehicles"]] == [("Ratha 1", "booked"), ("Ratha 2", "free")]


def test_booking_maintenance_and_ical_blocks_all_count_and_alternatives_are_offered(db, fleet):
    t, r1, r2 = fleet
    _stay(db, t, r1, D1, D2)
    _block(db, t, r2, D1 + timedelta(days=1), D2 + timedelta(days=3), reason="offline_booking")      # an iCal import
    out = ca.check(db, t.id, D1, D2, adults=2)
    assert not out["available"] and out["vehicle"] is None and out["reason"] == "taken"
    assert {v["property_name"]: v["status"] for v in out["vehicles"]} == {"Ratha 1": "booked", "Ratha 2": "booked_elsewhere"}
    alts = out["alternatives"]
    # one day earlier still ends before the iCal block starts on Ratha 2; later than that, Ratha 1 is free from D2
    assert alts[0] == {"check_in": (D1 - timedelta(days=1)).isoformat(), "check_out": (D2 - timedelta(days=1)).isoformat(),
                       "shift_days": -1, "vehicle": {"id": r2.id, "name": "Ratha 2"}}
    assert {"check_in": D2.isoformat(), "check_out": (D2 + timedelta(days=2)).isoformat(), "shift_days": 2,
            "vehicle": {"id": r1.id, "name": "Ratha 1"}} in alts
    assert all(date.fromisoformat(a["check_in"]) >= TODAY for a in alts)
    _block(db, t, r1, D2, D2 + timedelta(days=5), reason="maintenance")
    assert {v["status"] for v in ca.check(db, t.id, D2, D2 + timedelta(days=1))["vehicles"]} == {"maintenance", "booked_elsewhere"}


def test_noon_to_noon_back_to_back_trips_do_not_clash_and_a_cancelled_booking_frees_the_dates(db, fleet):
    t, r1, r2 = fleet
    _stay(db, t, r1, D1 - timedelta(days=2), D1)                  # ends the day ours starts
    _stay(db, t, r2, D1, D2, status="cancelled")
    out = ca.check(db, t.id, D1, D2)
    assert out["available"] and out["vehicle"]["id"] == r1.id
    assert all(v["free"] for v in out["vehicles"])


def test_a_booking_with_no_vehicle_yet_uses_up_one_of_the_shared_calendar(db, fleet):
    t, r1, r2 = fleet
    holder = _vehicle(db, t, "Unassigned (vehicle not chosen yet)")
    feed = ICalFeed(id=str(uuid.uuid4()), tenant_id=t.id, property_id=r1.id, name="Shared", export_token=uuid.uuid4().hex, is_active=True)
    db.add(feed)
    db.flush()
    for v in (r1, r2):
        db.add(ICalFeedVehicle(id=str(uuid.uuid4()), tenant_id=t.id, feed_id=feed.id, property_id=v.id, keywords=[v.name.lower()]))
    db.commit()
    _stay(db, t, r1, D1, D2)
    _stay(db, t, holder, D1, D2)                                   # needs the other caravan
    out = ca.check(db, t.id, D1, D2)
    assert not out["available"]
    assert {v["property_name"]: v["status"] for v in out["vehicles"]} == {"Ratha 1": "booked", "Ratha 2": "held_for_unassigned_booking"}
    assert "Unassigned (vehicle not chosen yet)" not in {v["property_name"] for v in out["vehicles"]}


def test_a_party_too_large_for_every_vehicle_is_said_so_and_past_dates_are_refused(db, fleet):
    t, _, _ = fleet
    big = ca.check(db, t.id, D1, D2, adults=9)
    assert not big["available"] and big["reason"] == "too_small" and big["alternatives"] == []
    past = ca.check(db, t.id, TODAY - timedelta(days=3), TODAY - timedelta(days=1))
    assert past["reason"] == "in_the_past" and past["vehicles"] == []


def test_the_fact_for_the_prompt_never_marks_a_taken_vehicle_available(db, fleet):
    t, r1, r2 = fleet
    _stay(db, t, r1, D1, D2)
    fact = ca.as_check_fact(ca.check(db, t.id, D1, D2, adults=2), 2, 0)
    assert fact["tool"] == "check_availability" and fact["args"]["checkin"] == D1.isoformat()
    assert [(r["property_name"], r["available"], r["reason"]) for r in fact["result"]] == [("Ratha 1", False, "unavailable"), ("Ratha 2", True, None)]
    assert "price_per_night" not in str(fact)


def test_another_tenants_bookings_and_vehicles_are_never_counted(db, fleet):
    t, r1, r2 = fleet
    other = _tenant(db)
    o1 = _vehicle(db, other, "Ratha 1")
    _stay(db, other, o1, D1, D2)
    out = ca.check(db, t.id, D1, D2)
    assert out["available"] and {v["property_id"] for v in out["vehicles"]} == {r1.id, r2.id}


def test_package_quotes_never_count_the_unassigned_placeholder_as_a_free_vehicle(db, fleet):
    t, r1, r2 = fleet
    _vehicle(db, t, "Unassigned (vehicle not chosen yet)")
    _stay(db, t, r1, D1, D2)
    _stay(db, t, r2, D1, D2)
    assert pps._open_vehicles(db, t.id, [], D1, D2, 2) == [
        {"property_id": r1.id, "property_name": "Ratha 1", "status": "unavailable"},
        {"property_id": r2.id, "property_name": "Ratha 2", "status": "unavailable"}]
