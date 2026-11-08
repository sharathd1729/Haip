"""Packs for every segment (Ops 2, gap 7): three flows, packs as data, per-property checklists, self check-in.

Caravan (Ratha) and villa (Jade) must not change: their pack definitions are compared with the snapshot taken before this
change (tests/fixtures/ops_packs/before_segment_packs.json), and their own test files (test_ops_files, test_ops_stays,
test_ops_today, test_ops_auto_messages ...) run unchanged.
"""

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.ops import OpsSettings
from app.models.ops_files import OpsChecklistTemplate, OpsFile
from app.models.property import Property, Stay
from app.models.user import UserRole
from app.services import ops_escalation_service as esc
from app.services import ops_pack_catalog as packs
from app.services import ops_pack_seed, ops_self_check_in
from app.services import ops_stay_service as stays
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, tenant
from tests.test_increment1_defect_specs import _h, _user

TODAY = date.today()
SNAPSHOT = Path(__file__).parent / "fixtures" / "ops_packs" / "before_segment_packs.json"

# business type -> (pack, flow, machine, unit word)
SEGMENTS = {
    "caravan": ("caravan_rv", "trip", "trip", "vehicle"),
    "villa_resort": ("villa", "whole_unit", "stay", "villa"),
    "farmhouse": ("villa", "whole_unit", "stay", "farmhouse"),
    "vacation_rental": ("vacation_rental", "whole_unit", "stay", "apartment"),
    "homestay": ("homestay", "whole_unit", "stay", "property"),
    "hotel": ("boutique_hotel", "room", "stay", "room"),
    "resort": ("boutique_hotel", "room", "stay", "room"),
    "guesthouse": ("boutique_hotel", "room", "stay", "room"),
}


def _tenant(db, business_type):
    t = tenant(db)
    t.business_type = business_type
    db.commit()
    return t


def _stay(db, t, p, *, start=3, nights=3, status="confirmed") -> Stay:
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Sample Guest", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    s = Stay(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        guest_id=g.id,
        property_id=p.id,
        check_in=TODAY + timedelta(days=start),
        check_out=TODAY + timedelta(days=start + nights),
        adults=2,
        status=status,
        total_amount=Decimal("20000"),
    )
    db.add(s)
    db.commit()
    return s


def _templates(db, tenant_id):
    return db.query(OpsChecklistTemplate).filter_by(tenant_id=tenant_id).all()


# ── Catalog ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("business_type", list(SEGMENTS))
def test_each_segment_gets_its_flow_pack_and_words(business_type):
    pack, flow, machine, unit = SEGMENTS[business_type]
    assert business_type in packs.BUSINESS_TYPES
    assert packs.pack_for_business_type(business_type) == pack
    assert packs.flow_of(pack) == flow and packs.machine(pack) == machine
    assert packs.unit_word_for(business_type) == unit
    spec = packs.get(pack)
    for key in ("duties", "issue_types", "paperwork", "addons", "auto_messages", "checklists", "host_label"):
        assert spec[key], key
    assert "Form C for foreign guests" in spec["paperwork"]


def test_three_flows_and_room_board_left_for_later():
    assert set(packs.FLOWS) == {"trip", "whole_unit", "room"}
    assert all(f["room_board"] is False for f in packs.FLOWS.values())  # the board is card Ops 2e
    assert packs.pack_for_business_type("travel_agency") is None and packs.pack_for_business_type(None) is None


def test_caravan_and_villa_packs_unchanged():
    before = json.loads(SNAPSHOT.read_text())
    for pack in ("caravan_rv", "villa"):
        now = json.loads(json.dumps(packs.PACKS[pack]))
        for key, value in before[pack].items():
            assert now[key] == value, (pack, key)
    assert packs.CANCELLABLE == tuple(before["_cancellable_all"])
    for bt, pack in before["_by_type"].items():
        assert packs.pack_for_business_type(bt) == pack
    assert packs.get("villa")["midstay_clean"] == {
        "every_days": stays.CLEAN_EVERY_DAYS,
        "min_nights": stays.CLEAN_MIN_NIGHTS,
    }


# ── Seeding ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("business_type", list(SEGMENTS))
def test_seed_creates_the_segments_templates_and_pack_data_once(db, business_type):
    pack = SEGMENTS[business_type][0]
    t = _tenant(db, business_type)
    out = ops_pack_seed.seed(db, t.id)
    db.commit()
    kinds = set(packs.get(pack)["checklists"])
    assert out["pack"] == pack and out["templates_created"] == len(kinds)
    assert {(r.pack, r.kind) for r in _templates(db, t.id)} == {(pack, k) for k in kinds}
    cfg = db.query(OpsSettings).filter_by(tenant_id=t.id).one().pack_config[pack]
    assert set(cfg) == set(ops_pack_seed.CONFIG_KEYS)
    assert cfg["duties"] == list(packs.get(pack)["duties"])
    again = ops_pack_seed.seed(db, t.id)
    db.commit()
    assert again["templates_created"] == 0 and again["config_keys_added"] == 0
    assert len(_templates(db, t.id)) == len(kinds)


def test_tenant_edits_survive_a_reseed(db):
    t = _tenant(db, "vacation_rental")
    ops_pack_seed.seed(db, t.id)
    mine = [{"key": "clean", "label": "Our own clean", "critical": True, "source": "staff", "photo": True}]
    ops_pack_seed.save_template(db, t.id, "vacation_rental", "readiness", "Our checklist", mine)
    ops_pack_seed.save_config(
        db, t.id, "vacation_rental", {"duties": ["housekeeping"], "auto_messages": {"pre_arrival": {"hours": 6}}}
    )
    db.commit()
    ops_pack_seed.seed(db, t.id)
    db.commit()
    row = db.query(OpsChecklistTemplate).filter_by(tenant_id=t.id, kind="readiness").one()
    assert row.name == "Our checklist" and row.items == mine
    cfg = ops_pack_seed.config(db, t.id)
    assert cfg["duties"] == ["housekeeping"]
    assert (
        cfg["auto_messages"]["pre_arrival"]["hours"] == 6
        and cfg["auto_messages"]["pre_arrival"]["when"] == "before_start"
    )


def test_existing_villa_template_is_never_overwritten(db):
    """Jade: a villa business whose checklist was created (or edited) before packs became data keeps it as it is."""
    t = _tenant(db, "villa_resort")
    db.add(
        OpsChecklistTemplate(tenant_id=t.id, pack="villa", kind="readiness", name="Jade's own", items=[{"key": "x"}])
    )
    db.commit()
    ops_pack_seed.seed(db, t.id)
    db.commit()
    rows = db.query(OpsChecklistTemplate).filter_by(tenant_id=t.id, pack="villa", kind="readiness").all()
    assert len(rows) == 1 and rows[0].name == "Jade's own"


def test_seeding_is_per_tenant(db):
    a, b = _tenant(db, "hotel"), _tenant(db, "hotel")
    ops_pack_seed.seed(db, a.id)
    db.commit()
    assert _templates(db, a.id) and not _templates(db, b.id)
    assert db.query(OpsSettings).filter_by(tenant_id=b.id).first() is None


# ── Files on the stay machine ───────────────────────────────────────────────


@pytest.mark.parametrize("business_type", ["vacation_rental", "homestay", "hotel", "farmhouse"])
def test_new_segments_get_a_stay_file_with_their_checklist(db, business_type):
    pack = SEGMENTS[business_type][0]
    t = _tenant(db, business_type)
    p = prop(db, t.id, "Unit 1")
    f = trips.ensure_file(db, t.id, _stay(db, t, p))
    db.commit()
    assert f.pack == pack and f.state == "preparing"
    keys = [i.key for i in trips.readiness_items(db, f)]
    assert keys == [i["key"] for i in packs.get(pack)["checklists"]["readiness"]["items"]]
    st = stays.stage(db, f)
    assert st["step_name"] == packs.get(pack)["step_names"][0]
    unit = packs.get(pack)["unit_word"].capitalize()
    assert any(task["label"] == f"{unit} ready to welcome" for task in st["tasks"])


def test_rental_staying_shows_no_meal_or_clean_steps_but_villa_does(db):
    def staying(bt):
        t = _tenant(db, bt)
        f = trips.ensure_file(db, t.id, _stay(db, t, prop(db, t.id, "U"), start=0, nights=6, status="checked_in"))
        db.commit()
        return {task["key"] for task in stays.stage(db, f)["tasks"]}

    assert {"clean", "meals"} <= staying("villa_resort")
    assert not {"clean", "meals"} & staying("vacation_rental")


def test_a_property_can_have_its_own_checklist(db):
    t = _tenant(db, "hotel")
    p1, p2 = prop(db, t.id, "Room 101"), prop(db, t.id, "Room 102")
    own = [{"key": "sea_view", "label": "Sea-view balcony swept", "critical": True, "source": "staff", "photo": True}]
    ops_pack_seed.save_template(db, t.id, "boutique_hotel", "readiness", "Suite ready", own, property_id=p1.id)
    db.commit()
    f1 = trips.ensure_file(db, t.id, _stay(db, t, p1))
    f2 = trips.ensure_file(db, t.id, _stay(db, t, p2))
    assert [i.key for i in trips.readiness_items(db, f1)] == ["sea_view"]
    assert "room" in [i.key for i in trips.readiness_items(db, f2)]
    assert ops_pack_seed.reset_property_template(db, t.id, "boutique_hotel", "readiness", p1.id)
    assert ops_pack_seed.template(db, t.id, "boutique_hotel", "readiness", p1.id).property_id is None


def test_trip_message_timings_come_from_the_pack_data(db):
    t = _tenant(db, "caravan")
    assert ops_pack_seed.message_hours(db, t.id, "caravan_rv", "crew_brief") == 72  # Ratha's behaviour unchanged
    ops_pack_seed.save_config(db, t.id, "caravan_rv", {"auto_messages": {"crew_brief": {"hours": 48}}})
    assert ops_pack_seed.message_hours(db, t.id, "caravan_rv", "crew_brief") == 48
    assert ops_pack_seed.message_hours(db, t.id, "caravan_rv", "helper_chase") == 24


# ── Self check-in ───────────────────────────────────────────────────────────


@pytest.fixture()
def rental(db):
    t = _tenant(db, "vacation_rental")
    seed_capabilities(db, t.id)
    p = prop(db, t.id, "Indiranagar 2BHK")
    return type(
        "R",
        (),
        {
            "t": t,
            "p": p,
            "owner": _user(db, t.id, UserRole.OWNER),
            "mgr": _user(db, t.id, UserRole.MANAGER),
            "foh": _user(db, t.id, UserRole.FOH),
            "mkt": _user(db, t.id, UserRole.MARKETING),
        },
    )()


CODE = "4821#"


def test_self_check_in_is_encrypted_masked_and_never_audited(client, db, rental):
    url = f"/api/v1/ops/properties/{rental.p.id}/self-check-in"
    r = client.put(
        url,
        json={"enabled": True, "lock_code": CODE, "steps": "Gate, lift to 3, door on the left"},
        headers=_h(rental.mgr),
    )
    assert r.status_code == 200, r.text
    assert r.json()["lock_code"] == CODE and r.json()["enabled"] is True
    raw = db.query(Property.self_check_in_enc).filter_by(id=rental.p.id).scalar()
    assert raw and CODE not in raw and "lift" not in raw
    staff_view = client.get(url, headers=_h(rental.foh)).json()
    assert staff_view["lock_code"] is None and staff_view["steps"] is None and staff_view["revealed"] is False
    assert staff_view["set"] == {"steps": True, "lock_code": True, "key_box": False}
    assert client.get(url, headers=_h(rental.mgr)).json()["lock_code"] == CODE
    assert client.get(url, headers=_h(rental.mkt)).status_code == 403
    assert client.put(url, json={"lock_code": "0000"}, headers=_h(rental.foh)).status_code == 403
    audits = db.query(AuditEvent).filter_by(tenant_id=rental.t.id, action="ops.self_check_in.changed").all()
    assert audits and all(CODE not in json.dumps(a.payload) for a in audits)
    assert ops_self_check_in.for_message(db, rental.t.id, rental.p.id)["lock_code"] == CODE


def test_self_check_in_needs_a_value_and_a_whole_unit_business(client, db, rental):
    url = f"/api/v1/ops/properties/{rental.p.id}/self-check-in"
    assert client.put(url, json={"enabled": True}, headers=_h(rental.mgr)).status_code == 422
    hotel = _tenant(db, "hotel")
    seed_capabilities(db, hotel.id)
    room = prop(db, hotel.id, "Room 1")
    mgr = _user(db, hotel.id, UserRole.MANAGER)
    r = client.put(f"/api/v1/ops/properties/{room.id}/self-check-in", json={"lock_code": "1"}, headers=_h(mgr))
    assert r.status_code == 409


def test_self_check_in_is_tenant_isolated(client, db, rental):
    other = _tenant(db, "vacation_rental")
    seed_capabilities(db, other.id)
    theirs = _user(db, other.id, UserRole.MANAGER)
    ops_self_check_in.update(db, rental.t.id, rental.p.id, enabled=None, values={"lock_code": CODE})
    db.commit()
    url = f"/api/v1/ops/properties/{rental.p.id}/self-check-in"
    assert client.get(url, headers=_h(theirs)).status_code == 404
    assert client.put(url, json={"lock_code": "1"}, headers=_h(theirs)).status_code == 404


def test_guest_issue_is_raised_one_step_when_nobody_is_on_site(db, rental):
    ops_self_check_in.update(db, rental.t.id, rental.p.id, enabled=True, values={"key_box": "Box by the gate, 1234"})
    staffed = prop(db, rental.t.id, "Staffed flat")
    item, _ = esc.create_item(
        db,
        rental.t.id,
        title="AC not cooling",
        severity="normal",
        duty="maintenance",
        category="ac",
        property_id=rental.p.id,
    )
    plain, _ = esc.create_item(
        db,
        rental.t.id,
        title="AC not cooling",
        severity="normal",
        duty="maintenance",
        category="ac",
        property_id=staffed.id,
    )
    money_item, _ = esc.create_item(
        db,
        rental.t.id,
        title="Refund deposit",
        severity="normal",
        duty="ops_manager",
        kind="manual",
        category="deposit",
        source="system",
        property_id=rental.p.id,
    )
    assert (item.severity, plain.severity, money_item.severity) == ("high", "normal", "normal")


# ── API: pack, checklists, business type ────────────────────────────────────


def test_api_pack_and_checklist_edit_per_property(client, db, rental):
    other = _tenant(db, "vacation_rental")
    foreign = prop(db, other.id, "Not yours")
    r = client.get("/api/v1/ops/pack", headers=_h(rental.foh))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["pack"], body["flow"], body["unit_word"]) == ("vacation_rental", "whole_unit", "apartment")
    assert body["self_check_in"] == {"offered": True, "suggested": True} and body["room_board"] is False
    items = [{"key": "clean", "label": "Deep clean", "critical": True, "source": "staff", "photo": True}]
    url = "/api/v1/ops/pack/checklists/readiness"
    assert client.put(url, json={"name": "X", "items": items}, headers=_h(rental.foh)).status_code == 403
    r = client.put(
        f"{url}?property_id={rental.p.id}", json={"name": "Flat 2 ready", "items": items}, headers=_h(rental.mgr)
    )
    assert r.status_code == 200 and r.json()["own_copy"] is True
    assert client.get(url, headers=_h(rental.mgr)).json()["own_copy"] is False  # the business default is untouched
    assert (
        client.put(
            f"{url}?property_id={foreign.id}", json={"name": "X", "items": items}, headers=_h(rental.mgr)
        ).status_code
        == 404
    )
    dup = items + items
    assert client.put(url, json={"name": "X", "items": dup}, headers=_h(rental.mgr)).status_code == 422
    r = client.put("/api/v1/ops/pack/config", json={"flow": "room"}, headers=_h(rental.mgr))
    assert r.status_code == 422  # a rental has one flow
    r = client.put(
        "/api/v1/ops/pack/config", json={"auto_messages": {"pre_arrival": {"hours": 12}}}, headers=_h(rental.mgr)
    )
    assert r.status_code == 200 and r.json()["auto_messages"]["pre_arrival"]["hours"] == 12


def test_choosing_a_segment_in_settings_switches_the_pack_on(client, db, rental):
    r = client.patch("/api/v1/tenants/me", json={"business_type": "hotel"}, headers=_h(rental.mgr))
    assert r.status_code == 403
    assert (
        client.patch("/api/v1/tenants/me", json={"business_type": "spaceship"}, headers=_h(rental.owner)).status_code
        == 422
    )
    r = client.patch("/api/v1/tenants/me", json={"business_type": "hotel"}, headers=_h(rental.owner))
    assert r.status_code == 200 and r.json()["business_type"] == "hotel"
    assert {row.pack for row in _templates(db, rental.t.id)} == {"boutique_hotel"}
    assert client.get("/api/v1/ops/pack", headers=_h(rental.mgr)).json()["unit_word"] == "room"
    assert db.query(AuditEvent).filter_by(tenant_id=rental.t.id, action="tenant.business_type_changed").count() == 1


def test_no_pack_means_409_on_the_pack_api(client, db):
    t = _tenant(db, None)
    seed_capabilities(db, t.id)
    assert client.get("/api/v1/ops/pack", headers=_h(_user(db, t.id, UserRole.MANAGER))).status_code == 409
    assert db.query(OpsFile).filter_by(tenant_id=t.id).count() == 0
