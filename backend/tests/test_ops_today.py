"""Ops Today (ops_today_service): unit cards, what needs a person (red first), the day plan, a calm day, isolation."""

from datetime import timedelta
from decimal import Decimal

from app.models.stay_finance import StayDeposit
from app.models.user import UserRole
from app.schemas.ops_files import ExtraIn
from app.services import ops_money as money
from app.services import ops_photo_intake as intake
from app.services import ops_today_service as today_svc
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, staff
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import (
    _green_all_critical,
    _pay,
    _ready_file,
    _stay,
    _tenant,
)


def _world(db):
    t = _tenant(db)
    r1, r2 = prop(db, t.id, "Ratha 1"), prop(db, t.id, "Ratha 2")
    prop(db, t.id, "Unassigned")  # the overflow placeholder is never a unit card
    w = type(
        "W",
        (),
        {
            "t": t,
            "r1": r1,
            "r2": r2,
            "driver": staff(db, t.id, "Suresh", "driver"),
            "helper": staff(db, t.id, "Raju", "driver"),
        },
    )()
    return w


def test_a_calm_business_has_no_needs(db):
    w = _world(db)
    out = today_svc.build(db, w.t.id)
    assert out["needs"] == [] and [u["name"] for u in out["units"]] == [
        "Ratha 1",
        "Ratha 2",
    ]
    assert all(u["status"] == "Free" for u in out["units"]) and out["unit_word"] == "vehicle"


def test_tomorrows_trip_with_open_checks_is_red_and_on_its_unit(db):
    w = _world(db)
    w.stay = _stay(db, w.t, w.r2, start=0, nights=2)  # leaves today: under 24 h
    _ready_file(db, w)
    out = today_svc.build(db, w.t.id)
    red = [n for n in out["needs"] if n["level"] == "red"]
    assert red and red[0]["unit"] == "Ratha 2" and "checks still open" in red[0]["title"]
    card = next(u for u in out["units"] if u["name"] == "Ratha 2")
    assert card["tone"] == "red" and card["status"] == "Getting ready" and card["ready_pct"] is not None
    assert out["day"][0]["what"] == "Ratha 2 leaves" and out["counts"]["leaving"] == 1


def test_a_staff_flag_shows_as_a_need_that_can_be_resolved(db):
    w = _world(db)
    w.stay = _stay(db, w.t, w.r1, start=5)
    f = _ready_file(db, w)
    intake.handle_text(db, w.t.id, w.driver, "issue AC making noise")
    out = today_svc.build(db, w.t.id)
    item = next(n for n in out["needs"] if n["action"] == "resolve_item")
    assert item["file_id"] == f.id and item["level"] == "red" and "AC making noise" in item["detail"]
    assert item["title"] == "Crew reported a problem"  # unit shown apart, sentence starts with a capital
    assert out["needs"][0]["level"] == "red"  # red first


def test_on_the_road_and_after_return(db):
    w = _world(db)
    w.stay = _stay(db, w.t, w.r1, start=-1, nights=2)
    f = _ready_file(db, w)
    _green_all_critical(db, f)
    _pay(db, w.stay, "126732")
    db.add(StayDeposit(tenant_id=w.t.id, stay_id=w.stay.id, amount=Decimal(10000), status="held"))
    db.flush()
    trips.refresh(db, f)
    trips.dispatch(db, f, 87396, "u1")
    money.propose_extra(db, f, ExtraIn(kind="upsell", label="Bonfire kit", amount=Decimal(2500)), "u1")
    out = today_svc.build(db, w.t.id)
    assert next(u for u in out["units"] if u["name"] == "Ratha 1")["status"] == "On the road"
    assert out["day"][0]["now"] is True and out["counts"]["away"] == 1
    assert any("extra" in n["title"] for n in out["needs"])
    trips.end_trip(db, f, 87900)
    f.returned_at -= timedelta(hours=50)
    out = today_svc.build(db, w.t.id)
    dep = next(n for n in out["needs"] if "Refund deposit" in n["title"])
    assert dep["level"] == "red"  # more than 48 h after return


def test_new_bookings_get_files_when_today_is_read(db):
    w = _world(db)
    _stay(db, w.t, w.r1, start=3)
    out = today_svc.build(db, w.t.id)
    assert any("Accept" in n["title"] for n in out["needs"])


def test_api_today_roles_and_tenants(client, db):
    w = _world(db)
    w.stay = _stay(db, w.t, w.r1, start=0)
    _ready_file(db, w)
    seed_capabilities(db, w.t.id)
    mgr, mkt = (
        _user(db, w.t.id, UserRole.MANAGER),
        _user(db, w.t.id, UserRole.MARKETING),
    )
    r = client.get("/api/v1/ops/files/today", headers=_h(mgr))
    assert r.status_code == 200 and r.json()["needs"]
    assert client.get("/api/v1/ops/files/today", headers=_h(mkt)).status_code == 403
    other = _tenant(db)
    seed_capabilities(db, other.id)
    o = client.get("/api/v1/ops/files/today", headers=_h(_user(db, other.id, UserRole.MANAGER))).json()
    assert o["needs"] == [] and o["units"] == []


def test_departure_wording_says_late_instead_of_zero_hours():
    assert today_svc.leaves_text(30.4) == "Leaves in 30 h"
    assert today_svc.leaves_text(0.4) == "Due to leave now"
    assert today_svc.leaves_text(-3.2) == "Was due to leave 3 h ago"
