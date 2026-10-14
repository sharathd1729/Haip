"""K-6: drafts from the rate plans, seasonal rates and routes a workspace already has. Drafts only; nothing guessed; nothing overwritten."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models.property import Property, RatePlan, SeasonalRate
from app.services import business_data_import_service as imp
from app.services import business_data_service as bds
from tests.test_business_data import TODAY, _workspace
from tests.test_increment1_defect_specs import _h


@pytest.fixture()
def w(db):
    return _workspace(db)


def caravan(db, w, **kw):
    p = Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name=kw.pop("name", "Caravan A"), slug=kw.pop("slug", "caravan-a"), type="caravan",
                 max_adults=4, max_children=0, price_per_km=Decimal("18"), routes=[{"from": "Bengaluru", "to": "Coorg", "km": 250}], **kw)
    db.add(p)
    db.flush()
    db.add(RatePlan(id=str(uuid.uuid4()), tenant_id=w.t.id, property_id=p.id, name="Standard", base_price_per_night=Decimal("18000"),
                    min_nights=2, duration_type="multiday", inclusions=["Driver"]))
    db.commit()
    return p


def test_it_creates_drafts_only_from_plans_and_routes_and_publishes_nothing(db, w):
    p = caravan(db, w)
    report = imp.draft_from_existing(db, w.t.id, w.owner.id)
    db.commit()
    assert {(c["kind"], c["key"]) for c in report.created} == {("destination", "coorg"), ("package", "caravan-a-multiday")}
    assert report.skipped == []
    assert bds.list_effective(db, w.t.id, "package") == [] and bds.list_effective(db, w.t.id, "destination") == []     # nothing is live
    pkg = bds.open_draft(db, w.t.id, "package", "caravan-a-multiday")
    assert pkg.status == "draft" and pkg.data["max_guests"] == 4 and pkg.data["min_nights"] == 2 and pkg.data["vehicle_property_ids"] == [p.id]
    assert pkg.data["extra_km_charge"] == {"per_km": "18.00"} and pkg.data["destination_keys"] == ["coorg"] and pkg.data["inclusions"] == ["Driver"]
    assert pkg.data["rates"][0]["amount"] == "18000.00" and "Check the unit" in pkg.change_note


def test_a_route_with_an_unknown_travel_time_cannot_be_published_until_a_person_fills_it_in(db, w):
    caravan(db, w)
    imp.draft_from_existing(db, w.t.id, w.owner.id)
    db.commit()
    dest = bds.open_draft(db, w.t.id, "destination", "coorg")
    assert dest.data["travel_hours_from_base"] == "0"
    with pytest.raises(bds.BusinessDataError) as e:
        bds.publish(db, w.t.id, dest.id, w.owner.id)
    assert any("travel time" in p for p in e.value.problems)
    bds.update_draft(db, w.t.id, dest.id, w.owner.id, data={**dest.data, "travel_hours_from_base": "5.5"})
    assert bds.publish(db, w.t.id, dest.id, w.owner.id).status == "published"


def test_seasonal_rates_split_the_base_window_so_nothing_overlaps(db, w):
    p = caravan(db, w)
    a, b = TODAY + timedelta(days=30), TODAY + timedelta(days=40)
    db.add(SeasonalRate(id=str(uuid.uuid4()), tenant_id=w.t.id, property_id=p.id, name="Peak", date_from=a.isoformat(), date_to=b.isoformat(),
                        price_per_night=Decimal("25000"), min_nights=1, priority=5))
    db.add(SeasonalRate(id=str(uuid.uuid4()), tenant_id=w.t.id, property_id=p.id, name="Old", date_from="2020-01-01", date_to="2020-02-01", price_per_night=Decimal("1")))
    db.commit()
    report = imp.draft_from_existing(db, w.t.id, w.owner.id)
    db.commit()
    assert report.skipped == []                                                                 # the schema's overlap check accepted every window
    rates = bds.open_draft(db, w.t.id, "package", "caravan-a-multiday").data["rates"]
    assert [(r["label"], r["valid_from"], r["valid_to"], r["amount"]) for r in rates] == [
        ("Standard", TODAY.isoformat(), (a - timedelta(days=1)).isoformat(), "18000.00"),
        ("Peak", a.isoformat(), b.isoformat(), "25000.00"),
        ("Standard", (b + timedelta(days=1)).isoformat(), (TODAY + timedelta(days=364)).isoformat(), "18000.00"),
    ]
    assert "Old" in bds.open_draft(db, w.t.id, "package", "caravan-a-multiday").change_note                    # the skipped past season is reported


def test_a_second_import_skips_what_exists_and_never_overwrites(db, w):
    caravan(db, w)
    imp.draft_from_existing(db, w.t.id, w.owner.id)
    db.commit()
    again = imp.draft_from_existing(db, w.t.id, w.owner.id)
    assert again.created == [] and {s["key"] for s in again.skipped} == {"coorg", "caravan-a-multiday"}
    assert len(bds.history(db, w.t.id, "package", "caravan-a-multiday")) == 1


def test_same_day_plans_price_per_package_and_other_tenants_are_untouched(db, w):
    p = caravan(db, w)
    db.add(RatePlan(id=str(uuid.uuid4()), tenant_id=w.t.id, property_id=p.id, name="Day trip", base_price_per_night=Decimal("9000"), min_nights=1, duration_type="same_day"))
    db.commit()
    other = _workspace(db)
    imp.draft_from_existing(db, w.t.id, w.owner.id)
    db.commit()
    day = bds.open_draft(db, w.t.id, "package", "caravan-a-same-day").data
    assert day["rates"][0]["unit"] == "package" and day["min_nights"] == 0 and day["product"] == "same_day"
    assert bds.history(db, other.t.id, "package", "caravan-a-multiday") == []


def test_endpoint_needs_settings_manage_and_reports_what_it_did(db, client, w):
    caravan(db, w)
    assert client.post("/api/v1/business-data/import-existing", headers=_h(w.ro)).status_code == 403
    r = client.post("/api/v1/business-data/import-existing", headers=_h(w.owner))
    assert r.status_code == 200, r.text
    assert len(r.json()["created"]) == 2 and r.json()["skipped"] == []
    assert client.get("/api/v1/business-data/effective/package", headers=_h(w.owner)).json() == []          # still nothing live
