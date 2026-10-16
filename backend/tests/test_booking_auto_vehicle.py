"""A booking made without choosing a vehicle goes to the first free one: Ratha 1, and an overlapping one to Ratha 2. When every
vehicle is taken it is refused (never double-booked). The "Unassigned" placeholder is never a candidate. Other workspaces'
vehicles are never touched."""
import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

from app.models.base import gen_uuid  # noqa: E402
from app.models.property import BlockedDate, Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import booking_service as bsvc  # noqa: E402


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _d(n):
    return date.today() + timedelta(days=n)


def _prop(db, tid, name, active=True):
    p = Property(id=gen_uuid(), tenant_id=tid, name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}", type="caravan", is_active=active)
    db.add(p)
    db.commit()
    return p


def _book(client, tu, **over):
    body = {"guest_name": "Asha", "guest_phone": f"+9198{uuid.uuid4().int % 10**8:08d}", "check_in": _d(10).isoformat(), "check_out": _d(12).isoformat()}
    body.update(over)
    return client.post("/api/v1/bookings", json=body, headers=_h(tu))


def test_first_booking_takes_ratha_1_and_an_overlapping_one_takes_ratha_2(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    r2, r1 = _prop(db, tid, "Ratha 2"), _prop(db, tid, "Ratha 1")              # created out of order on purpose
    a = _book(client, tenant_and_user)
    b = _book(client, tenant_and_user)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    ids = {s.id: s.property_id for s in db.query(Stay).filter_by(tenant_id=tid).all()}
    assert ids[a.json()["id"]] == r1.id and ids[b.json()["id"]] == r2.id


def test_every_vehicle_taken_is_a_409_and_nothing_is_created(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _prop(db, tid, "Ratha 1"), _prop(db, tid, "Ratha 2")
    assert _book(client, tenant_and_user).status_code == 201
    assert _book(client, tenant_and_user).status_code == 201
    r = _book(client, tenant_and_user)
    assert r.status_code == 409 and "vehicle" in r.json()["detail"].lower()
    assert db.query(Stay).filter_by(tenant_id=tid).count() == 2


def test_later_dates_start_again_from_ratha_1(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    r1 = _prop(db, tid, "Ratha 1"), _prop(db, tid, "Ratha 2")
    _book(client, tenant_and_user)
    later = _book(client, tenant_and_user, check_in=_d(30).isoformat(), check_out=_d(32).isoformat())
    assert db.query(Stay).filter_by(id=later.json()["id"]).one().property_id == r1[0].id


def test_a_blocked_vehicle_is_skipped(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    r1, r2 = _prop(db, tid, "Ratha 1"), _prop(db, tid, "Ratha 2")
    db.add(BlockedDate(id=gen_uuid(), tenant_id=tid, property_id=r1.id, blocked_from=_d(9).isoformat(), blocked_to=_d(11).isoformat(), reason="maintenance", is_active=True))
    db.commit()
    s = _book(client, tenant_and_user)
    assert db.query(Stay).filter_by(id=s.json()["id"]).one().property_id == r2.id


def test_the_placeholder_and_inactive_vehicles_are_never_picked(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _prop(db, tid, "Unassigned (vehicle not chosen yet)")
    _prop(db, tid, "Ratha 0", active=False)
    assert bsvc.pick_free_property(db, tid, _d(3), _d(5)) is None
    r1 = _prop(db, tid, "Ratha 1")
    assert bsvc.pick_free_property(db, tid, _d(3), _d(5)).id == r1.id


def test_names_sort_naturally(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _prop(db, tid, "Ratha 10"), _prop(db, tid, "Ratha 2")
    assert bsvc.pick_free_property(db, tid, _d(3), _d(5)).name == "Ratha 2"


def test_another_workspaces_vehicles_are_never_used(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _prop(db, other.id, "Ratha 1")
    assert bsvc.pick_free_property(db, tid, _d(3), _d(5)) is None
    assert _book(client, tenant_and_user).status_code == 409


def test_a_chosen_vehicle_is_still_honoured(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _prop(db, tid, "Ratha 1")
    r2 = _prop(db, tid, "Ratha 2")
    s = _book(client, tenant_and_user, property_id=r2.id, internal_notes="Black Ratha")
    assert s.status_code == 201
    row = db.query(Stay).filter_by(id=s.json()["id"]).one()
    assert row.property_id == r2.id and row.internal_notes == "Black Ratha"


def test_the_unassigned_placeholder_is_never_offered_in_the_caravan_picker(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _prop(db, tid, "Unassigned (legacy bookings -- reassign manually)")
    r1 = _prop(db, tid, "Ratha 1")
    names = [p["name"] for p in client.get("/api/v1/bookings/properties", headers=_h(tenant_and_user)).json()]
    assert names == ["Ratha 1"] and r1.id


def test_the_calendar_hides_the_placeholder_row_unless_it_holds_a_real_booking(client, db, tenant_and_user):
    from app.models.guest import Guest
    tid = tenant_and_user["tenant"].id
    ph = _prop(db, tid, "Unassigned (legacy bookings -- reassign manually)")
    _prop(db, tid, "Ratha 1")
    url = f"/api/v1/calendar?from_date={_d(0).isoformat()}&to_date={_d(30).isoformat()}"
    # the shared calendar's own record of an event is a block on the placeholder: that alone must not bring the row back
    db.add(BlockedDate(id=gen_uuid(), tenant_id=tid, property_id=ph.id, blocked_from=_d(3).isoformat(), blocked_to=_d(4).isoformat(), reason="other", is_active=True))
    db.commit()
    rows = client.get(url, headers=_h(tenant_and_user)).json()["properties"]
    assert [r["property_name"] for r in rows] == ["Ratha 1"]
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Overflow", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=ph.id, check_in=_d(5), check_out=_d(7), adults=2, status="confirmed"))
    db.commit()
    rows = client.get(url, headers=_h(tenant_and_user)).json()["properties"]
    assert sorted(r["property_name"] for r in rows) == ["Ratha 1", "Unassigned (legacy bookings -- reassign manually)"]
