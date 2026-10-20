"""Time-aware clash rule (owner decision, Oct 2026): with pickup/return times on both bookings, [pickup, return) overlap blocks
and a gap under 2 hours is a warning; without times the date rule is unchanged (the iCal import, the paid-quote link and the
sales agent call it without times and must see exactly the old answer). POST and PATCH /bookings refuse a real clash with a
plain-words 409. Another workspace's bookings never count."""
import uuid
from datetime import date, timedelta

import pytest

from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.user import UserRole
from app.services import booking_clash as bc
from app.services import booking_service as bsvc
from tests.test_business_data import _tenant
from tests.test_increment1_defect_specs import _h, _user

D = date.today() + timedelta(days=20)


def _d(n):
    return D + timedelta(days=n)


@pytest.fixture()
def t(db):
    tenant = _tenant(db)
    props = []
    for name in ("Ratha 1", "Ratha 2"):
        p = Property(id=gen_uuid(), tenant_id=tenant.id, name=name, slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
        db.add(p)
        props.append(p)
    db.commit()
    return type("T", (), {"t": tenant, "r1": props[0], "r2": props[1], "owner": _user(db, tenant.id, UserRole.OWNER)})()


def stay(db, tid, prop, ci, co, cit=None, cot=None, name="Manisha Rao"):
    g = Guest(id=gen_uuid(), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=ci, check_out=co, status="confirmed",
             check_in_time=cit, check_out_time=cot)
    db.add(s)
    db.commit()
    return s


def test_overlapping_times_block_and_the_message_names_the_other_trip(db, t):
    stay(db, t.t.id, t.r1, _d(0), _d(2), "12:00", "12:00")
    hits = bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(2), _d(3), check_in_time="10:00", check_out_time="12:00")
    assert [h["type"] for h in hits] == ["booking"] and hits[0]["guest"] == "Manisha Rao"
    st = bc.states(db, t.t.id, _d(2), _d(3), "10:00", "12:00")
    r1 = next(v for v in st["vehicles"] if v["name"] == "Ratha 1")
    assert r1["state"] == "booked"
    assert r1["message"] == f"Ratha 1 is out with Manisha Rao until 12:00 pm on {bc.day(_d(2))}. Pick Ratha 2 or other dates."
    assert st["auto"]["name"] == "Ratha 2"


def test_a_gap_under_two_hours_is_a_warning_not_a_block(db, t):
    stay(db, t.t.id, t.r1, _d(0), _d(2), "12:00", "12:00")
    assert bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(2), _d(3), check_in_time="13:00", check_out_time="12:00") == []
    tight = bsvc.turnarounds(db, t.t.id, t.r1.id, _d(2), _d(3), "13:00", "12:00")
    assert len(tight) == 1 and tight[0]["gap_minutes"] == 60 and tight[0]["returns_before"] is True
    st = bc.states(db, t.t.id, _d(2), _d(3), "13:00", "12:00")
    assert [v["state"] for v in st["vehicles"]] == ["tight", "free"]
    assert "Less than 2 hours to clean" in st["vehicles"][0]["message"]
    assert st["auto"]["name"] == "Ratha 2"                         # first free prefers a comfortable turnaround
    assert bsvc.turnarounds(db, t.t.id, t.r1.id, _d(2), _d(3), "14:00", "12:00") == []      # exactly 2 h: fine


def test_times_let_a_day_trip_fit_before_a_later_pickup(db, t):
    stay(db, t.t.id, t.r1, _d(0), _d(2), "16:00", "12:00")
    assert bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(0), _d(0), check_in_time="08:00", check_out_time="13:00") == []
    assert bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(0), _d(0))                    # by date it would clash


def test_without_times_the_date_rule_is_unchanged(db, t):
    """Regression for the iCal import / paid quote link / sales agent, which call without times."""
    stay(db, t.t.id, t.r1, _d(0), _d(2), "12:00", "12:00")                    # has times; the caller does not
    stay(db, t.t.id, t.r2, _d(5), _d(7))                                       # no times at all
    assert bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(2), _d(4)) == []        # noon to noon: back to back is fine
    assert len(bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(1), _d(3))) == 1
    assert len(bsvc.find_conflicts(db, t.t.id, t.r1.id, _d(1), _d(1))) == 1    # a same-day stay occupies its day
    assert bsvc.pick_free_property(db, t.t.id, _d(1), _d(3)).id == t.r2.id
    assert bsvc.pick_free_property(db, t.t.id, _d(6), _d(8)).id == t.r1.id
    # one side without times -> the date rule even when the caller passes times
    assert len(bsvc.find_conflicts(db, t.t.id, t.r2.id, _d(6), _d(8), check_in_time="18:00", check_out_time="10:00")) == 1
    assert bsvc.turnarounds(db, t.t.id, t.r2.id, _d(7), _d(8), "12:30", "12:00") == []


def test_another_workspace_never_counts(db, t):
    other = _tenant(db)
    p = Property(id=gen_uuid(), tenant_id=other.id, name="Ratha 1", slug=f"o-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
    db.add(p)
    db.commit()
    stay(db, other.id, p, _d(0), _d(2), "12:00", "12:00")
    st = bc.states(db, t.t.id, _d(0), _d(2), "12:00", "12:00")
    assert [v["state"] for v in st["vehicles"]] == ["free", "free"]
    assert {v["property_id"] for v in st["vehicles"]} == {t.r1.id, t.r2.id}


def test_post_bookings_refuses_a_real_clash_in_plain_words(client, db, t):
    stay(db, t.t.id, t.r1, _d(0), _d(2), "12:00", "12:00", name="Neha Kulkarni")
    body = {"guest_name": "Asha", "guest_phone": f"+9198{uuid.uuid4().int % 10**8:08d}", "property_id": t.r1.id,
            "check_in": _d(1).isoformat(), "check_out": _d(3).isoformat(), "check_in_time": "12:00", "check_out_time": "12:00"}
    r = client.post("/api/v1/bookings", json=body, headers=_h(t.owner))
    assert r.status_code == 409
    assert r.json()["detail"] == f"Ratha 1 is booked {bc.span(_d(0), _d(2))} (Neha Kulkarni). Pick Ratha 2 or other dates."
    ok = client.post("/api/v1/bookings", json={**body, "check_in": _d(2).isoformat(), "check_in_time": "13:30"}, headers=_h(t.owner))
    assert ok.status_code == 201, ok.text                                     # a tight turnaround is allowed


def test_patch_moving_the_pickup_into_another_trip_is_refused(client, db, t):
    stay(db, t.t.id, t.r1, _d(0), _d(2), "12:00", "12:00")
    mine = stay(db, t.t.id, t.r1, _d(2), _d(3), "15:00", "12:00", name="Kiran")
    r = client.patch(f"/api/v1/bookings/{mine.id}", json={"check_in_time": "11:00"}, headers=_h(t.owner))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "date_conflict"
    assert client.patch(f"/api/v1/bookings/{mine.id}", json={"check_in_time": "14:30"}, headers=_h(t.owner)).status_code == 200
