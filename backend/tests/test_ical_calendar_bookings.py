"""A complete event of a shared Google Calendar becomes a real booking (vehicle chosen later, like a hotel room).

Pinned here: which events qualify; the booking lands on the "Unassigned" property when no vehicle is named and holds one
vehicle until a real one is picked; the advance becomes one payment; edits and deletes in Google update or cancel the
booking but never undo a human's choice (checked in, cancelled, vehicle picked); two vehicles in one event stay a block;
a link without vehicle keywords never makes bookings; bookings without a vehicle count against the vehicles that are free.
"""
import pytest

from app.models.ical_feed import ICalEventBooking
from app.models.property import BlockedDate, Property, Stay
from app.models.stay_finance import StayPayment
from app.models.task import Task
from app.services import booking_service as bsvc
from app.services import ical_booking_service as ibs
from app.services import vehicle_pool
from app.services.calculator_service import CalculatorService
from tests.test_ical_feeds import _auth, _d, _feed, _ics, _prop, _tenant
from tests.test_ical_shared_calendar import _active, _event, _sync, shared  # noqa: F401  (shared is a fixture)

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _desc(name="Asha", phone="+91 98000 11111", total="Rs 30,000", advance="Rs 10,000"):
    lines = [f"Guest Name: {name}"]
    if phone:
        lines.append(f"Contact Number: {phone}")
    if total:
        lines.append(f"Total Booking Amount: {total}")
    if advance:
        lines.append(f"Advance Received: {advance}")
    lines.append("Guests: 2 Adults + 1 Child")
    return "\n".join(lines)


def _stays(db, tid):
    return db.query(Stay).filter_by(tenant_id=tid).order_by(Stay.check_in).all()


def _open_tasks(db, tid, prefix):
    return db.query(Task).filter(Task.tenant_id == tid, Task.is_done.is_(False), Task.title.like(prefix + "%")).all()


def _ev(uid="b1@g", summary="Asha| Jishanth", n=10, nights=2, **kw):
    return _event(uid, summary, _desc(**kw), start=_d(n), end=_d(n + nights))


# ── which events qualify ─────────────────────────────────────────────────────

def test_a_complete_event_with_no_vehicle_becomes_an_unassigned_booking(db, shared):
    r = _sync(db, shared["feed"], _ev())
    assert r["bookings_created"] == 1 and r["needs_vehicle"] == 0
    (stay,) = _stays(db, shared["tid"])
    assert stay.property_id == shared["placeholder"].id and stay.status == "confirmed"
    assert (stay.check_in.isoformat(), stay.check_out.isoformat()) == (_d(10), _d(12))
    assert float(stay.total_amount) == 30000.0 and (stay.adults, stay.children) == (2, 1)
    assert stay.channel_source == "google_calendar"
    (pay,) = db.query(StayPayment).filter_by(stay_id=stay.id).all()
    assert float(pay.amount) == 10000.0 and pay.kind == "payment"
    assert db.query(BlockedDate).filter(BlockedDate.notes.like("ical:%")).count() == 0       # a booking, not a block
    (task,) = _open_tasks(db, shared["tid"], ibs.ASSIGN_PREFIX)
    assert "Asha" in task.title and task.guest_id == stay.guest_id


def test_syncing_again_changes_nothing(db, shared):
    _sync(db, shared["feed"], _ev())
    r = _sync(db, shared["feed"], _ev())
    assert r["bookings_created"] == 0 and r["bookings_updated"] == 0
    (stay,) = _stays(db, shared["tid"])
    assert db.query(StayPayment).filter_by(stay_id=stay.id).count() == 1
    assert len(_open_tasks(db, shared["tid"], ibs.ASSIGN_PREFIX)) == 1
    assert db.query(ICalEventBooking).count() == 1


@pytest.mark.parametrize("kwargs", [{"phone": None}, {"total": None}, {"name": ""}])
def test_an_incomplete_event_stays_a_block(db, shared, kwargs):
    r = _sync(db, shared["feed"], _ev(**kwargs))
    assert r["bookings_created"] == 0 and _stays(db, shared["tid"]) == []
    assert _active(db, shared["white"]) and _active(db, shared["black"])               # held on both, as before


def test_a_one_day_event_with_no_trip_dates_is_not_trusted_as_a_booking(db, shared):
    _sync(db, shared["feed"], _ev(nights=1))
    assert _stays(db, shared["tid"]) == []


def test_an_event_naming_two_vehicles_stays_a_block_on_both(db, shared):
    _sync(db, shared["feed"], _ev(summary="Krithika| white and black ratha"))
    assert _stays(db, shared["tid"]) == []
    assert _active(db, shared["white"]) == _active(db, shared["black"]) != []


def test_a_link_without_vehicle_keywords_never_makes_bookings(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid, "Caravan 1")
    feed = _feed(db, tid, prop.id, name="Airbnb")
    _sync(db, feed, _ev())
    assert _stays(db, tid) == [] and _active(db, prop)


# ── the vehicle ──────────────────────────────────────────────────────────────

def test_a_named_vehicle_is_booked_directly_with_no_assign_task(db, shared):
    _sync(db, shared["feed"], _ev(summary="Asha| white ratha| Jishanth"))
    (stay,) = _stays(db, shared["tid"])
    assert stay.property_id == shared["white"].id
    assert _open_tasks(db, shared["tid"], ibs.ASSIGN_PREFIX) == []


def test_a_named_vehicle_that_is_taken_falls_back_to_unassigned_and_says_so(db, shared):
    _sync(db, shared["feed"], _ev("one@g", "Asha| white ratha"))
    _sync(db, shared["feed"], _ev("one@g", "Asha| white ratha"), _ev("two@g", "Ravi| white ratha", phone="+91 98111 22222", name="Ravi"))
    stays = {s.guest_id: s for s in _stays(db, shared["tid"])}
    assert len(stays) == 2
    assert sorted(s.property_id for s in stays.values()) == sorted([shared["white"].id, shared["placeholder"].id])
    assert len(_open_tasks(db, shared["tid"], "Vehicle taken")) == 1


def test_picking_the_vehicle_at_check_in_sticks_and_closes_the_task(db, shared, client):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    r = client.patch(f"/api/v1/bookings/{stay.id}", json={"property_id": shared["black"].id}, headers=_auth(shared["tu"]))
    assert r.status_code == 200, r.text
    _sync(db, shared["feed"], _ev())                                  # the calendar still names no vehicle
    db.refresh(stay)
    assert stay.property_id == shared["black"].id
    assert _open_tasks(db, shared["tid"], ibs.ASSIGN_PREFIX) == []


def test_the_event_naming_a_vehicle_later_moves_an_unassigned_booking_only_if_it_is_free(db, shared):
    _sync(db, shared["feed"], _ev())
    _sync(db, shared["feed"], _ev(summary="Asha| black ratha"))
    (stay,) = _stays(db, shared["tid"])
    assert stay.property_id == shared["black"].id


# ── bookings without a vehicle use up a vehicle ──────────────────────────────

def test_an_unassigned_booking_keeps_one_vehicle_free_for_itself(db, shared):
    _sync(db, shared["feed"], _ev())
    ci, co = _stays(db, shared["tid"])[0].check_in, _stays(db, shared["tid"])[0].check_out
    tid, white, black = shared["tid"], shared["white"], shared["black"]
    assert bsvc.find_conflicts(db, tid, white.id, ci, co) == []                     # one vehicle can still go to someone else
    other = Stay(tenant_id=tid, guest_id=_stays(db, tid)[0].guest_id, property_id=white.id, check_in=ci, check_out=co, status="confirmed")
    db.add(other)
    db.commit()
    short = bsvc.find_conflicts(db, tid, black.id, ci, co)                           # the last one is spoken for
    assert [c["type"] for c in short] == ["unassigned_bookings"]
    assert CalculatorService()._is_available(db, black.id, tid, ci.isoformat(), co.isoformat()) is False


def test_the_unassigned_booking_itself_can_take_the_last_free_vehicle(db, shared):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    assert bsvc.find_conflicts(db, shared["tid"], shared["white"].id, stay.check_in, stay.check_out, exclude_stay_id=stay.id) == []


def test_more_unassigned_bookings_than_vehicles_raises_one_task(db, shared):
    evs = [_ev(f"u{i}@g", f"G{i}| Jishanth", name=f"G{i}", phone=f"+91 9800{i}00000") for i in range(3)]
    _sync(db, shared["feed"], *evs)
    assert len(_stays(db, shared["tid"])) == 3
    assert len(_open_tasks(db, shared["tid"], "Not enough vehicles")) == 1
    assert vehicle_pool.over_capacity_days(db, shared["tid"], [shared["white"].id, shared["black"].id],
                                           _stays(db, shared["tid"])[0].check_in, _stays(db, shared["tid"])[0].check_out)


def test_a_property_in_no_pool_is_unaffected(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    villa = _prop(db, tid, "Villa")
    assert vehicle_pool.shortage_days(db, tid, villa.id, vehicle_pool.date.today(), vehicle_pool.date.today()) == []


# ── edits and deletes in Google ──────────────────────────────────────────────

def test_editing_the_event_updates_the_booking_and_the_advance(db, shared):
    _sync(db, shared["feed"], _ev())
    r = _sync(db, shared["feed"], _event("b1@g", "Asha| Jishanth", _desc(total="Rs 45,000", advance="Rs 15,000"), start=_d(11), end=_d(14)))
    assert r["bookings_updated"] == 1 and r["bookings_created"] == 0
    (stay,) = _stays(db, shared["tid"])
    assert (stay.check_in.isoformat(), stay.check_out.isoformat(), float(stay.total_amount)) == (_d(11), _d(14), 45000.0)
    (pay,) = db.query(StayPayment).filter_by(stay_id=stay.id).all()
    assert float(pay.amount) == 15000.0


def test_once_the_guest_is_checked_in_the_calendar_no_longer_changes_the_booking(db, shared):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    stay.status = "checked_in"
    db.commit()
    _sync(db, shared["feed"], _event("b1@g", "Asha| Jishanth", _desc(total="Rs 99,000"), start=_d(11), end=_d(14)))
    db.refresh(stay)
    assert float(stay.total_amount) == 30000.0 and stay.check_in.isoformat() == _d(10)
    _sync(db, shared["feed"])                                             # event deleted: still no change
    db.refresh(stay)
    assert stay.status == "checked_in"


def test_deleting_the_event_cancels_a_confirmed_booking_and_a_returning_event_makes_a_new_one(db, shared):
    _sync(db, shared["feed"], _ev())
    r = _sync(db, shared["feed"])
    assert r["bookings_cancelled"] == 1
    (stay,) = _stays(db, shared["tid"])
    assert stay.status == "cancelled" and db.query(ICalEventBooking).count() == 0
    assert _open_tasks(db, shared["tid"], ibs.ASSIGN_PREFIX) == []
    _sync(db, shared["feed"], _ev())
    assert sorted(s.status for s in _stays(db, shared["tid"])) == ["cancelled", "confirmed"]


def test_a_booking_the_team_cancelled_is_not_revived_by_the_calendar(db, shared):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    stay.status = "cancelled"
    db.commit()
    _sync(db, shared["feed"], _ev())
    db.refresh(stay)
    assert stay.status == "cancelled" and len(_stays(db, shared["tid"])) == 1


def test_a_finished_trip_that_drops_out_of_the_calendar_is_left_alone(db, shared):
    _sync(db, shared["feed"], _ev(n=-12, nights=2))
    assert len(_stays(db, shared["tid"])) == 1
    _sync(db, shared["feed"])
    (stay,) = _stays(db, shared["tid"])
    assert stay.status == "confirmed"


# ── isolation, endpoint, helpers ─────────────────────────────────────────────

def test_bookings_belong_to_the_feeds_tenant_only(db, shared):
    other = _tenant(db)
    _sync(db, shared["feed"], _ev())
    assert db.query(Stay).filter_by(tenant_id=other).count() == 0
    assert all(s.tenant_id == shared["tid"] for s in db.query(Stay).all())
    assert db.query(ICalEventBooking).filter(ICalEventBooking.tenant_id != shared["tid"]).count() == 0


def test_the_feed_list_reports_how_many_bookings_the_calendar_made(db, shared, client):
    _sync(db, shared["feed"], _ev())
    listed = client.get("/api/v1/ical-feeds", headers=_auth(shared["tu"])).json()
    assert listed[0]["bookings"] == 1


def test_a_clash_when_picking_the_vehicle_is_refused_like_any_other_booking(db, shared, client):
    _sync(db, shared["feed"], _ev("one@g", "Asha| white ratha"))
    _sync(db, shared["feed"], _ev("one@g", "Asha| white ratha"), _ev("two@g", "Ravi", phone="+91 98111 22222", name="Ravi"))
    unassigned = next(s for s in _stays(db, shared["tid"]) if s.property_id == shared["placeholder"].id)
    r = client.patch(f"/api/v1/bookings/{unassigned.id}", json={"property_id": shared["white"].id}, headers=_auth(shared["tu"]))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "date_conflict"


@pytest.mark.parametrize("text,expected", [("5", (5, 0)), ("2 Adults + 1 Child", (2, 1)), ("7 pax + 1 toddler", (7, 1)), (None, (1, 0)), ("", (1, 0))])
def test_head_count(text, expected):
    assert ibs.head_count(text) == expected
