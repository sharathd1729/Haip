"""Ops phase 2, fleet (migration 180): papers with expiry, the licence and dispatch rules ported from the Ratha prototype
(workflow.ts assign, derive.ts vehicle/people alerts), defects that keep a vehicle off sale, services by km, stock at par,
the Fleet API (happy path, roles, cross-tenant) and the Today needs."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.models.audit_event import AuditEvent
from app.models.ops_fleet import OpsDefect, OpsPaper
from app.models.property import BlockedDate
from app.models.user import UserRole
from app.schemas.ops import StaffCreate, StaffUpdate
from app.schemas.ops_files import CrewIn
from app.schemas.ops_fleet import DefectIn, InventoryCountIn, InventoryIn, PaperIn, ServiceDoneIn, ServiceIn
from app.services import booking_service, ops_fleet_view, ops_today_service, staff_service
from app.services import ops_fleet_service as fleet
from app.services import ops_money as money
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, staff
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import TODAY, _actor_u1, _green_all_critical, _pay, _ready_file, _stay, _tenant  # noqa: F401


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    return type(
        "W",
        (),
        {
            "t": t,
            "p": p,
            "stay": _stay(db, t, p),
            "driver": staff(db, t.id, "Suresh", "driver"),
            "helper": staff(db, t.id, "Raju", "driver"),
        },
    )()


def _ready_to_dispatch(db, w):
    f = _ready_file(db, w)
    _green_all_critical(db, f)
    _pay(db, w.stay, "126732")
    trips.refresh(db, f)
    assert f.state == "dispatch_ready"
    return f


# ── Papers (derive.ts: <= 30 days amber, <= 7 days or expired red) ──────────


def test_paper_levels_and_words():
    assert fleet.paper_level(TODAY + timedelta(days=31), TODAY) is None
    assert fleet.paper_level(TODAY + timedelta(days=30), TODAY) == "amber"
    assert fleet.paper_level(TODAY + timedelta(days=7), TODAY) == "red"
    assert fleet.paper_level(TODAY - timedelta(days=1), TODAY) == "red"
    assert fleet.paper_level(None, TODAY) is None
    p = OpsPaper(name="Insurance", expires_on=TODAY - timedelta(days=2))
    assert fleet.paper_words(p, TODAY).startswith("Expired on")
    p.expires_on = TODAY
    assert fleet.paper_words(p, TODAY) == "Expires today"


def test_a_new_paper_replaces_the_old_one_of_the_same_kind(db, w):
    old = fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="insurance", expires_on=TODAY))
    new = fleet.add_paper(
        db, w.t.id, PaperIn(property_id=w.p.id, kind="insurance", expires_on=TODAY + timedelta(days=365))
    )
    db.refresh(old)
    assert not old.active and new.active and new.name == "Insurance"
    with pytest.raises(HTTPException):
        fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="hmv_licence"))
    with pytest.raises(HTTPException):
        fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, staff_id=w.driver.id, kind="other"))


def test_paper_file_type_and_size_are_checked():
    assert fleet.check_file(b"%PDF-1.4 ...", "application/pdf") == "pdf"
    for raw, ct, words in (
        (b"\x00\x01", "image/jpeg", "does not look like"),
        (b"<html>", "text/html", "JPG, PNG"),
        (b"\xff\xd8\xff" + b"0" * (6 * 1024 * 1024), "image/jpeg", "5 MB"),
    ):
        with pytest.raises(HTTPException) as e:
            fleet.check_file(raw, ct)
        assert words in e.value.detail


# ── Licence rule (workflow.ts assign) ───────────────────────────────────────


def test_a_driver_whose_licence_ends_before_the_trip_cannot_be_assigned(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    fleet.set_licence(db, w.t.id, w.driver.id, "KA01 2020", w.stay.check_out - timedelta(days=1))
    with pytest.raises(HTTPException) as e:
        trips.set_crew(db, f, CrewIn(driver_staff_id=w.driver.id, helper_staff_id=w.helper.id), "u1")
    assert e.value.status_code == 422 and "licence expires" in e.value.detail and "Suresh" in e.value.detail
    fleet.set_licence(db, w.t.id, w.driver.id, "KA01 2020", w.stay.check_out)  # expiring on the last day is fine
    trips.set_crew(db, f, CrewIn(driver_staff_id=w.driver.id, helper_staff_id=w.helper.id), "u1")
    assert money.details(f).driver_staff_id == w.driver.id


def test_staff_licence_is_kept_as_a_paper(db, w):
    s = staff_service.create_staff(
        db, w.t.id, StaffCreate(name="Mohan", phone="+919845012345", licence_number="KA05", licence_expires_on=TODAY)
    )
    out = staff_service.to_out(db, s)
    assert out["licence_number"] == "KA05" and out["licence_expires_on"] == TODAY
    staff_service.update_staff(db, w.t.id, s.id, StaffUpdate(licence_expires_on=TODAY + timedelta(days=400)))
    lic = fleet.licence(db, w.t.id, s.id)
    assert lic.number == "KA05" and lic.expires_on == TODAY + timedelta(days=400)
    assert db.query(OpsPaper).filter_by(staff_id=s.id).count() == 1


# ── Dispatch rules ──────────────────────────────────────────────────────────


def test_dispatch_is_refused_for_an_expired_or_expiring_paper(db, w):
    f = _ready_to_dispatch(db, w)
    fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="puc", expires_on=TODAY - timedelta(days=1)))
    with pytest.raises(HTTPException) as e:
        trips.dispatch(db, f, 1000, "u1")
    assert "Pollution certificate (PUC) expired on" in e.value.detail
    fleet.add_paper(
        db, w.t.id, PaperIn(property_id=w.p.id, kind="puc", expires_on=w.stay.check_out - timedelta(days=1))
    )
    with pytest.raises(HTTPException) as e:
        trips.dispatch(db, f, 1000, "u1")
    assert "before the trip ends" in e.value.detail
    fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="puc", expires_on=TODAY + timedelta(days=200)))
    fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="other", name="Club card", expires_on=TODAY))
    assert trips.dispatch(db, f, 1000, "u1").state == "on_trip"  # a non-critical paper never blocks


def test_a_critical_defect_blocks_dispatch_and_sale_until_closed(db, w):
    f = _ready_to_dispatch(db, w)
    d = fleet.add_defect(
        db,
        w.t.id,
        DefectIn(property_id=w.p.id, title="AC compressor dead", severity="critical"),
        actor_id="u1",
        today=TODAY,
    )
    block = db.get(BlockedDate, d.block_id)
    assert block.is_active and block.blocked_from == TODAY.isoformat() and block.reason == "maintenance"
    clash = booking_service.find_conflicts(db, w.t.id, w.p.id, TODAY + timedelta(days=1), TODAY + timedelta(days=2))
    assert any(c["type"] == "block" for c in clash)
    with pytest.raises(HTTPException) as e:
        trips.dispatch(db, f, 1000, "u1")
    assert "Open defect: AC compressor dead" in e.value.detail
    fleet.close_defect(db, w.t.id, d.id, "Compressor replaced", "u1")
    assert not db.get(BlockedDate, d.block_id).is_active
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ops.defect.closed").count() == 1
    with pytest.raises(HTTPException):
        fleet.close_defect(db, w.t.id, d.id, None, "u1")
    assert trips.dispatch(db, f, 1000, "u1").state == "on_trip"


def test_a_normal_defect_does_not_block(db, w):
    d = fleet.add_defect(db, w.t.id, DefectIn(property_id=w.p.id, title="Curtain hook loose"))
    assert d.block_id is None


def test_blocks_roll_forward_while_the_defect_is_open(db, w):
    d = fleet.add_defect(db, w.t.id, DefectIn(property_id=w.p.id, title="Brakes", severity="critical"), today=TODAY)
    later = TODAY + timedelta(days=3)
    assert fleet.keep_blocks(db, w.t.id, later) == 1
    assert db.get(BlockedDate, d.block_id).blocked_to == (later + timedelta(days=fleet.BLOCK_DAYS)).isoformat()
    assert fleet.keep_blocks(db, w.t.id, later) == 0


def test_a_critical_checklist_photo_opens_one_defect(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    assert fleet.defect_from_photo(db, f, "ac", "AC: not cooling", "Photo from Raju") is not None
    assert fleet.defect_from_photo(db, f, "ac", "AC: not cooling", "again") is None
    assert db.query(OpsDefect).filter_by(file_id=f.id, status="open").count() == 1


# ── Services, km and stock ──────────────────────────────────────────────────


def test_service_due_by_km_uses_the_vehicles_last_reading(db, w):
    f = _ready_to_dispatch(db, w)
    trips.dispatch(db, f, 87396, "u1")
    trips.end_trip(db, f, 88792, actor_id="u1")
    assert fleet.vehicle_km(db, w.t.id, w.p.id) == 88792
    s = fleet.add_service(db, w.t.id, ServiceIn(property_id=w.p.id, name="Engine oil", due_km=89500), "u1")
    assert fleet.service_state(s, 88792, TODAY) == ("amber", "Due in 708 km")
    assert fleet.service_state(s, 89600, TODAY)[0] == "red"
    later = fleet.add_service(
        db, w.t.id, ServiceIn(property_id=w.p.id, name="Tyres", due_on=TODAY + timedelta(days=60)), "u1"
    )
    assert fleet.service_state(later, 88792, TODAY)[0] is None
    assert fleet.service_state(later, 88792, TODAY + timedelta(days=61))[0] == "red"
    fleet.service_done(db, w.t.id, s.id, ServiceDoneIn(), "u1", TODAY)
    assert s.status == "done" and s.done_km == 88792
    with pytest.raises(HTTPException):
        fleet.add_service(db, w.t.id, ServiceIn(property_id=w.p.id, name="Nothing"), "u1")


def test_stock_below_par_is_a_restock_need(db, w):
    it = fleet.add_item(db, w.t.id, InventoryIn(property_id=w.p.id, name="Towels", par=8, count=8), "u1")
    assert ops_fleet_view.needs(db, w.t.id, TODAY) == {}
    fleet.set_count(db, w.t.id, it.id, InventoryCountIn(count=5), "u1")
    n = ops_fleet_view.needs(db, w.t.id, TODAY)[w.p.id]
    assert n[0]["title"] == "Restock Towels (5 of 8)" and n[0]["level"] == "amber" and n[0]["action"] == "open_fleet"
    with pytest.raises(HTTPException):
        fleet.add_item(db, w.t.id, InventoryIn(property_id=w.p.id, name="Towels", par=2), "u1")


def test_today_shows_fleet_problems_on_the_unit_card(db, w):
    fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="insurance", expires_on=TODAY + timedelta(days=5)))
    fleet.set_licence(db, w.t.id, w.driver.id, "KA", TODAY + timedelta(days=20))
    out = ops_today_service.build(db, w.t.id)
    titles = {n["title"]: n for n in out["needs"]}
    ins = next(n for t, n in titles.items() if t.startswith("Insurance"))
    lic = next(n for t, n in titles.items() if t.startswith("HMV driving licence"))
    assert (
        ins["level"] == "red" and lic["level"] == "amber" and lic["unit"] == "Suresh" and lic["action"] == "open_staff"
    )
    unit = next(u for u in out["units"] if u["property_id"] == w.p.id)
    assert unit["tone"] == "red"


def test_fleet_card(db, w):
    fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="permit", expires_on=TODAY + timedelta(days=100)))
    card = next(c for c in ops_fleet_view.fleet(db, w.t.id, TODAY) if c["property_id"] == w.p.id)
    assert card["tone"] == "ok" and card["papers"][0]["name"] == "Permit"
    assert "Insurance" in card["missing_papers"] and "Permit" not in card["missing_papers"]


def test_another_tenant_sees_and_touches_nothing(db, w):
    d = fleet.add_defect(db, w.t.id, DefectIn(property_id=w.p.id, title="Leak", severity="critical"))
    other = _tenant(db)
    op = prop(db, other.id, "Other 1")
    assert all(c["property_id"] == op.id for c in ops_fleet_view.fleet(db, other.id, TODAY))
    with pytest.raises(HTTPException) as e:
        fleet.close_defect(db, other.id, d.id, None, "u1")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        fleet.add_defect(db, other.id, DefectIn(property_id=w.p.id, title="x"))
    with pytest.raises(HTTPException):
        fleet.add_paper(db, other.id, PaperIn(staff_id=w.driver.id, kind="hmv_licence"))


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture()
def api(db, w):
    seed_capabilities(db, w.t.id)
    return type(
        "A",
        (),
        {
            "mgr": _user(db, w.t.id, UserRole.MANAGER),
            "foh": _user(db, w.t.id, UserRole.FOH),
            "mkt": _user(db, w.t.id, UserRole.MARKETING),
        },
    )()


def test_api_fleet_flow(client, db, w, api):
    r = client.post(
        "/api/v1/ops/fleet/defects",
        json={"property_id": w.p.id, "title": "Leak", "severity": "critical"},
        headers=_h(api.foh),
    )
    assert r.status_code == 201, r.text
    card = next(c for c in r.json() if c["property_id"] == w.p.id)
    assert card["tone"] == "red" and card["defects"][0]["title"] == "Leak"
    r = client.post(
        "/api/v1/ops/fleet/inventory",
        json={"property_id": w.p.id, "name": "Towels", "par": 8, "count": 3},
        headers=_h(api.foh),
    )
    item = next(c for c in r.json() if c["property_id"] == w.p.id)["inventory"][0]
    assert item["low"] is True
    r = client.patch(f"/api/v1/ops/fleet/inventory/{item['id']}", json={"count": 8}, headers=_h(api.foh))
    assert next(c for c in r.json() if c["property_id"] == w.p.id)["inventory"][0]["low"] is False
    r = client.post(
        "/api/v1/ops/fleet/papers",
        json={"staff_id": w.driver.id, "kind": "hmv_licence", "expires_on": str(TODAY + timedelta(days=3))},
        headers=_h(api.foh),
    )
    assert r.status_code == 201
    papers = client.get(f"/api/v1/ops/fleet/papers?staff_id={w.driver.id}", headers=_h(api.foh)).json()
    assert papers[0]["level"] == "red"
    defect_id = card["defects"][0]["id"]
    assert client.post(f"/api/v1/ops/fleet/defects/{defect_id}/close", json={}, headers=_h(api.foh)).status_code == 403
    r = client.post(f"/api/v1/ops/fleet/defects/{defect_id}/close", json={"note": "fixed"}, headers=_h(api.mgr))
    assert r.status_code == 200 and next(c for c in r.json() if c["property_id"] == w.p.id)["defects"] == []


def test_api_roles_and_tenants(client, db, w, api):
    assert client.get("/api/v1/ops/fleet", headers=_h(api.mkt)).status_code == 403
    assert (
        client.post(
            "/api/v1/ops/fleet/services", json={"property_id": w.p.id, "name": "Oil", "due_km": 1}, headers=_h(api.mkt)
        ).status_code
        == 403
    )
    assert client.get("/api/v1/ops/fleet", headers=_h(api.foh)).status_code == 200
    d = fleet.add_defect(db, w.t.id, DefectIn(property_id=w.p.id, title="Leak"))
    db.commit()
    other = _tenant(db)
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert client.post(f"/api/v1/ops/fleet/defects/{d.id}/close", json={}, headers=_h(om)).status_code == 404
    assert (
        client.post("/api/v1/ops/fleet/defects", json={"property_id": w.p.id, "title": "x"}, headers=_h(om)).status_code
        == 404
    )
    assert all(c["property_id"] != w.p.id for c in client.get("/api/v1/ops/fleet", headers=_h(om)).json())


def test_api_staff_carries_the_licence(client, db, w, api):
    r = client.post(
        "/api/v1/ops/staff",
        json={
            "name": "Mohan",
            "phone": "+919845012399",
            "duties": [{"duty": "driver"}],
            "licence_number": "KA05",
            "licence_expires_on": "2030-01-01",
        },
        headers=_h(api.mgr),
    )
    assert r.status_code == 201, r.text
    row = next(s for s in client.get("/api/v1/ops/staff", headers=_h(api.foh)).json() if s["name"] == "Mohan")
    assert row["licence_number"] == "KA05" and row["licence_expires_on"] == "2030-01-01"


def test_paper_dates_are_dates(db, w):
    p = fleet.add_paper(db, w.t.id, PaperIn(property_id=w.p.id, kind="fc", expires_on=date(2030, 1, 1)))
    assert p.expires_on == date(2030, 1, 1)
