"""Rathaa commercial master (21 Oct 2026): the catalogue file, its import as drafts, price floors and partner-only (B2B) packages."""
import importlib.util
import json
import os
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models.business_record import BusinessRecord
from app.models.knowledge import KnowledgeEntry
from app.schemas.business_data import validate_data
from app.services import business_data_service as bds
from app.services import package_pricing_service as pps
from app.services import sales_gateway as gw
from tests.test_business_data import TODAY, package, w  # noqa: F401  (w is a fixture)
from tests.test_package_pricing import publish, vehicle

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "import_ratha_catalogue.py")
_spec = importlib.util.spec_from_file_location("import_ratha_catalogue", _SCRIPT)
imp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(imp)

with open(imp.DATA, encoding="utf-8") as _fh:
    CATALOGUE = json.load(_fh)


def test_every_catalogue_record_is_valid_and_in_publish_order():
    built = imp.build(CATALOGUE)
    for kind, key, data in built:
        model, problems = validate_data(kind, data)
        assert model is not None, f"{kind} {key}: {problems}"
    kinds = [k for k, _, _ in built]
    assert kinds.index("package") > max(i for i, k in enumerate(kinds) if k == "destination")
    assert kinds.index("itinerary") > max(i for i, k in enumerate(kinds) if k == "package")
    pkgs = {key: data for kind, key, data in built if kind == "package"}
    assert pkgs["rathaa-base-b2b"]["audience"] == "b2b" and pkgs["mysuru-escape"].get("audience", "retail") == "retail"
    assert all(p["gst_percent"] == "18" for p in pkgs.values())
    assert {r["amount"]: r["floor_amount"] for r in pkgs["mysuru-coorg"]["rates"]} == {"65000": "60000"}
    itins = [data for kind, _, data in built if kind == "itinerary"]
    for it in itins:                                       # every itinerary fits its package's nights
        for pk in it["package_keys"]:
            p = pkgs[pk]
            assert p.get("min_nights", 0) <= it["nights"] <= (p.get("max_nights") if p.get("max_nights") is not None else 60)


def test_peak_dates_have_no_rate_and_package_trips_end_before_the_peak():
    two_night = imp._rates({"band": ["65000", "60000"], "unit": "package"}, CATALOGUE["valid"], 2)
    assert two_night[0]["valid_to"] == "2026-12-26" and two_night[1]["valid_from"] == "2027-01-02"
    per_day = imp._rates({"band": ["45000", "35000"], "unit": "day"}, CATALOGUE["valid"], 3)
    assert per_day[0]["valid_to"] == "2026-12-28"


def test_import_is_a_dry_run_unless_applied_then_drafts_only_and_idempotent(db, w):  # noqa: F811
    tid = w.t.id
    out = imp.run(db, tid, CATALOGUE)                     # a dry run writes nothing (no rollback needed: SQLite would drop fixtures)
    assert not out["invalid"] and db.query(BusinessRecord).filter_by(tenant_id=tid).count() == 0
    assert len(out["drafted"]) == len(imp.build(CATALOGUE))

    out = imp.run(db, tid, CATALOGUE, apply=True)
    db.commit()
    recs = db.query(BusinessRecord).filter_by(tenant_id=tid).all()
    assert len(recs) == len(imp.build(CATALOGUE)) and {r.status for r in recs} == {"draft"}
    assert {r.created_by for r in recs} == {w.owner.id}
    kb = db.query(KnowledgeEntry).filter_by(tenant_id=tid, source="owner_notes").all()
    assert len(kb) == len(CATALOGUE["knowledge"]) and {e.review_status for e in kb} == {"pending"}
    assert gw.list_packages(db, tid).flags == ["none_published"]           # nothing reaches a guest before publishing

    again = imp.run(db, tid, CATALOGUE, apply=True)
    assert not again["drafted"] and len(again["draft_exists"]) == len(imp.build(CATALOGUE)) and not again["kb_created"]


def test_drafts_stay_in_their_own_workspace(db, w):  # noqa: F811
    from tests.test_business_data import _workspace
    other = _workspace(db)
    imp.run(db, w.t.id, CATALOGUE, apply=True)
    db.commit()
    assert db.query(BusinessRecord).filter_by(tenant_id=other.t.id).count() == 0


# ── price floor ─────────────────────────────────────────────────────────────────────────────────────────────

def _band_package(**over):
    rate = {"label": "Band", "valid_from": TODAY.isoformat(), "valid_to": (TODAY + timedelta(days=400)).isoformat(),
            "amount": "35000", "floor_amount": "30000", "unit": "package"}
    return package(name="Mysuru Escape", product="same_day", min_nights=0, included_km=None, extra_km_charge=None,
                   extra_guest_charge=None, rates=[rate], **over)


def test_floor_above_amount_is_invalid():
    bad = _band_package()
    bad["rates"][0]["floor_amount"] = "36000"
    model, problems = validate_data("package", bad)
    assert model is None and any("floor_amount" in p for p in problems)


@pytest.mark.parametrize("percent,status", [("10", "applied"), ("14", "applied"), ("20", "refused")])
def test_a_discount_never_goes_below_the_floor(db, w, percent, status):  # noqa: F811
    vehicle(db, w, adults=6)
    publish(db, w, "mysuru-escape", _band_package())
    publish(db, w, "default", {"max_discount_percent": "23", "requires_approval_above_percent": "15", "approver_roles": ["owner"]},
            kind="discount_policy")
    d = TODAY + timedelta(days=5)
    q = pps.quote(db, w.t.id, "mysuru-escape", d, d, 2, discount_percent=Decimal(percent))
    assert q.ok and q.discount["status"] == status
    if status == "refused":
        assert "lowest price" in q.discount["reason"] and q.taxable == Decimal("35000.00")


# ── partner-only (B2B) packages ─────────────────────────────────────────────────────────────────────────────

def test_b2b_package_is_never_shown_or_quoted_to_a_guest_but_staff_can_price_it(db, w):  # noqa: F811
    vehicle(db, w)
    publish(db, w, "rathaa-base-b2b", package(name="Rathaa Base", audience="b2b"))
    publish(db, w, "coorg", package())
    keys = [p["key"] for p in gw.list_packages(db, w.t.id).data]
    assert keys == ["coorg"]
    assert gw.get_package(db, w.t.id, "rathaa-base-b2b").flags == ["b2b_only"]
    ci, co = TODAY + timedelta(days=10), TODAY + timedelta(days=12)
    res = gw.quote_package(db, w.t.id, "rathaa-base-b2b", ci, co, 2)
    assert not res.ok and res.flags == ["refused:b2b_only"] and "amount" not in json.dumps(res.data)
    assert gw.match_package(db, w.t.id, {"destination": "Rathaa Base"}) is None
    assert pps.quote(db, w.t.id, "rathaa-base-b2b", ci, co, 2).ok                 # the staff calculator still prices it


def test_ai_view_shows_extra_hours_at_actuals_and_gst_on_top_but_never_the_floor(db, w):  # noqa: F811
    vehicle(db, w, adults=6)
    publish(db, w, "mysuru-escape", _band_package(extra_hour_charge={"per_hour": "2500"},
                                                   at_actuals=["JLR safari, meals and activities (paid to JLR)"]))
    view = gw.get_package(db, w.t.id, "mysuru-escape").data
    assert view["extra_hour_charge"] == {"amount": "2500.00"} and view["gst_added_on_top"] is True
    assert view["billed_at_actuals"] == ["JLR safari, meals and activities (paid to JLR)"]
    assert "30000" not in json.dumps(view) and "floor" not in json.dumps(view)
