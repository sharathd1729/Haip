"""scripts/route_packages.py: vehicle-based package drafts become route-based packages (Black/White duplicates merged, same
prices), through business_data_service versioning. The dry run writes nothing."""
import importlib.util
import os
import uuid
from datetime import timedelta

import pytest

from app.models.audit_event import AuditEvent
from app.models.business_record import BusinessRecord
from app.models.property import Property
from app.services import business_data_service as bds
from tests.test_business_data import TODAY, _workspace

_spec = importlib.util.spec_from_file_location("route_packages", os.path.join(os.path.dirname(__file__), "..", "scripts", "route_packages.py"))
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def _pkg(name, product, amount, vehicle, unit="package"):
    return {"name": name, "product": product, "max_guests": 6, "vehicle_property_ids": [vehicle], "day_count": "noon_to_noon",
            "rates": [{"label": "Standard", "valid_from": TODAY.isoformat(), "valid_to": (TODAY + timedelta(days=300)).isoformat(),
                       "amount": amount, "unit": unit}], "inclusions": ["Driver"], "exclusions": ["Tolls"], "gst_percent": "12"}


@pytest.fixture()
def w(db):
    w = _workspace(db)
    ids = {}
    for colour in ("Black", "White"):
        p = Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name=f"Ratha {colour}", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan",
                     max_adults=8, max_children=0)
        db.add(p)
        ids[colour] = p.id
    db.commit()
    names = {"Black": "Black Caravan — The Night Voyager", "White": "White Caravan — The Light Wanderer"}
    for colour, vid in ids.items():
        for suffix, product, amount, unit in (("same day", "same_day", "25000", "package"), ("overnight", "overnight", "42000", "package"),
                                              ("multiday", "multiday", "0", "day")):
            key = f"{colour.lower()}-{suffix.replace(' ', '-')}"
            bds.create_draft(db, w.t.id, "package", key, _pkg(f"{names[colour]} - {suffix}", product, amount, vid, unit), w.owner.id)
    db.commit()
    return w


def counts(db, tid):
    db.flush()
    return (db.query(BusinessRecord).filter_by(tenant_id=tid).count(), db.query(AuditEvent).filter_by(tenant_id=tid).count(),
            sorted((r.key, r.status) for r in db.query(BusinessRecord).filter_by(tenant_id=tid).all()))


def test_route_name():
    assert rp.route_name("Black Caravan — The Night Voyager - same day") == "Same-day ride"
    assert rp.route_name("White Caravan — The Light Wanderer - multiday") == "Multi-day trip"
    assert rp.route_name("Coorg 48-hour Retreat") == "Coorg 48-hour Retreat"


def test_dry_run_writes_nothing_and_says_what_it_would_do(db, w):
    before = counts(db, w.t.id)
    plan = rp.plan(db, w.t.id)
    assert counts(db, w.t.id) == before
    assert sorted(g["new_key"] for g in plan["merge"]) == ["multi-day-trip", "overnight-escape", "same-day-ride"]
    multi = next(g for g in plan["merge"] if g["new_key"] == "multi-day-trip")
    assert multi["priced"] is False and len(multi["members"]) == 2 and multi["data"]["vehicle_property_ids"] == []


def test_apply_merges_the_black_and_white_duplicates(db, w):
    done = rp.apply(db, w.t.id, rp.plan(db, w.t.id), publish=True)
    db.commit()
    assert sorted(done["created"]) == ["multi-day-trip", "overnight-escape", "same-day-ride"]
    assert sorted(done["published"]) == ["overnight-escape", "same-day-ride"] and len(done["rejected"]) == 6
    same = bds.get_effective(db, w.t.id, "package", "same-day-ride", TODAY)
    assert same.data["vehicle_property_ids"] == [] and same.data["rates"][0]["amount"] == "25000.00" and same.data["name"] == "Same-day ride"
    assert bds.open_draft(db, w.t.id, "package", "multi-day-trip") is not None          # price 0: stays a draft for the owner
    old = db.query(BusinessRecord).filter_by(tenant_id=w.t.id, key="black-same-day").one()
    assert old.status == "rejected" and "same-day-ride" in old.rejected_reason
    again = rp.plan(db, w.t.id)
    assert again["merge"] == []                                                          # nothing left to convert


def test_different_prices_are_not_merged(db, w):
    rec = bds.open_draft(db, w.t.id, "package", "white-overnight")
    data = dict(rec.data)
    data["rates"] = [{**data["rates"][0], "amount": "45000"}]
    bds.update_draft(db, w.t.id, rec.id, w.owner.id, data=data)
    db.commit()
    plan = rp.plan(db, w.t.id)
    assert [c["name"] for c in plan["conflicts"]] == ["Overnight escape"]
    assert "overnight-escape" not in [g["new_key"] for g in plan["merge"]]
