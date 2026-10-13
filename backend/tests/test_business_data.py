"""Structured business records: typed validation, draft/publish/rollback lifecycle, effective dating, audit, API and isolation.

What these pin (docs/ai/RATHA_KB_EVOLUTION.md):
  * exact commercial values are typed fields, and contradictory or incomplete data is refused with a plain-language reason;
  * guest-facing reads (get_effective) never return a draft, a rejected, an inactive or a not-yet-started version;
  * a published version never changes: a new version supersedes it, rollback copies an old one into a NEW version;
  * every state change is audited with a field-level diff; tenants never see each other's records.
"""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

import pytest

from app.models.audit_event import AuditEvent
from app.models.business_record import BusinessRecord
from app.models.capability import Capability
from app.models.module import Module, WorkspaceModule
from app.models.user import UserRole
from app.schemas.business_data import validate_data
from app.services import business_data_service as svc
from app.models.tenant import Tenant
from tests.conftest import seed_capabilities
from tests.test_increment1_defect_specs import _h, _user

TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date()      # the tenant's own calendar day (Tenant.timezone defaults to Asia/Kolkata)


def package(**over):
    base = {
        "name": "Signature Caravan - Coorg", "product": "multiday", "max_guests": 4, "min_nights": 2, "included_km": 600,
        "inclusions": ["Caravan with driver", "Bed linen"], "exclusions": ["Meals", "Toll"],
        "rates": [{"label": "Standard", "valid_from": f"{TODAY.year}-01-01", "valid_to": f"{TODAY.year + 1}-12-31", "amount": "18000", "unit": "night"}],
        "extra_guest_charge": {"free_guests": 2, "per_guest_per_night": "1500"}, "extra_km_charge": {"per_km": "18"},
        "charges": [{"name": "Bonfire", "kind": "experience", "amount": "1500", "unit": "per_stay"}],
        "destination_keys": [], "gst_percent": "12", "quote_valid_days": 3,
    }
    base.update(over)
    return base


def coorg():
    return {"name": "Coorg", "description": "Coffee estates and mist.", "distance_km_from_base": 250, "travel_hours_from_base": 5.5,
            "stops": [{"name": "Madikeri", "order": 1, "overnight": True}], "best_months": [10, 11, 12, 1, 2]}


@pytest.fixture()
def w(db):
    return _workspace(db)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"bd-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.commit()
    seed_capabilities(db, t.id)                       # the real default role matrix, including settings.manage
    return t


def _workspace(db):
    t = _tenant(db)
    if db.query(Module).filter_by(code="ai_concierge").first() is None:
        db.add(Module(id=str(uuid.uuid4()), code="ai_concierge", name="AI"))
        db.flush()
    mod = db.query(Module).filter_by(code="ai_concierge").first()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=t.id, module_id=mod.id, enabled=True))
    db.commit()
    return type("W", (), {"t": t, "owner": _user(db, t.id, UserRole.OWNER), "ro": _user(db, t.id, UserRole.READ_ONLY),
                          "mgr": _user(db, t.id, UserRole.MANAGER)})()


def audits(db, tid, suffix):
    db.flush()                                        # the test session does not autoflush
    return db.query(AuditEvent).filter_by(tenant_id=tid, action=f"business_record.{suffix}").all()


# ─── typed validation ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mutation,needle", [
    ({"rates": [{"label": "a", "valid_from": "2026-01-01", "valid_to": "2026-06-30", "amount": "1", "unit": "night"},
                {"label": "b", "valid_from": "2026-06-01", "valid_to": "2026-12-31", "amount": "2", "unit": "night"}]}, "overlap"),
    ({"inclusions": ["Meals"], "exclusions": ["meals"]}, "both included and excluded"),
    ({"min_nights": 5, "max_nights": 2}, "max_nights is below min_nights"),
    ({"rates": [{"label": "a", "valid_from": "2026-06-01", "valid_to": "2026-01-01", "amount": "1"}]}, "valid_to is before valid_from"),
    ({"rates": [{"label": "a", "valid_from": "2026-01-01", "valid_to": "2026-02-01", "amount": "-5"}]}, "amount"),
    ({"rates": []}, "rates"),
    ({"max_guests": 0}, "max_guests"),
    ({"gst_percent": "40"}, "gst_percent"),
    ({"prices": "18000"}, "prices"),                                   # unknown field: refused, not silently dropped
    ({"product": "same_day", "min_nights": 2}, "same-day"),
])
def test_contradictory_or_incomplete_package_data_is_refused_with_a_reason(mutation, needle):
    model, problems = validate_data("package", package(**mutation))
    assert model is None and any(needle in p for p in problems), problems


def test_non_overlapping_seasons_for_the_same_product_and_overlapping_ones_for_different_products_are_fine():
    ok = package(rates=[
        {"label": "Peak", "valid_from": "2026-12-01", "valid_to": "2027-01-10", "amount": "24000", "unit": "night"},
        {"label": "Off", "valid_from": "2027-01-11", "valid_to": "2027-03-31", "amount": "18000", "unit": "night"},
        {"label": "Weekend", "valid_from": "2026-12-01", "valid_to": "2027-03-31", "amount": "26000", "unit": "night", "days_of_week": [4, 5]},
    ])
    assert validate_data("package", ok)[0] is not None


@pytest.mark.parametrize("kind,data,needle", [
    ("destination", {**coorg(), "stops": [{"name": "a", "order": 1}, {"name": "b", "order": 1}]}, "same order"),
    ("destination", {**coorg(), "distance_km_from_base": 900, "travel_hours_from_base": 2}, "average speed"),
    ("itinerary", {"name": "x", "destination_key": "coorg", "nights": 1, "days": [{"day": 1, "title": "a"}, {"day": 3, "title": "b"}]}, "without gaps"),
    ("itinerary", {"name": "x", "destination_key": "coorg", "nights": 1, "days": [{"day": 1, "title": "a"}, {"day": 2, "title": "b"}, {"day": 3, "title": "c"}]}, "do not fit"),
    ("payment_policy", {"advance_percent": 30, "balance_due_days_before_checkin": 7, "instalments": [{"label": "a", "percent": 30, "due_days_before_checkin": 30}, {"label": "b", "percent": 50, "due_days_before_checkin": 7}]}, "add up to 100"),
    ("cancellation_policy", {"tiers": [{"days_before": 30, "refund_percent": 50}, {"days_before": 7, "refund_percent": 90}]}, "must not grow"),
    ("discount_policy", {"max_discount_percent": 10, "requires_approval_above_percent": 15}, "above max_discount_percent"),
    ("reseller_terms", {"tiers": [{"name": "A", "commission_percent": 10}, {"name": "a", "commission_percent": 12}]}, "same name"),
    ("stay_rules", {"check_in_time": "25:00", "check_out_time": "11:00"}, "check_in_time"),
])
def test_other_kinds_refuse_contradictions(kind, data, needle):
    model, problems = validate_data(kind, data)
    assert model is None and any(needle in p for p in problems), problems


# ─── lifecycle: drafts are invisible, published is in force, history is kept ──────────────────────────────

def test_a_draft_never_reaches_a_guest_facing_read_and_publishing_makes_it_live(db, w):
    d = svc.create_draft(db, w.t.id, "package", "coorg-signature", package(), w.owner.id)
    assert d.status == "draft" and d.version == 1
    assert svc.get_effective(db, w.t.id, "package", "coorg-signature") is None
    assert svc.list_effective(db, w.t.id, "package") == []
    svc.publish(db, w.t.id, d.id, w.owner.id)
    live = svc.get_effective(db, w.t.id, "package", "coorg-signature")
    assert live.id == d.id and live.status == "published" and live.effective_from == TODAY
    assert [r.key for r in svc.list_effective(db, w.t.id, "package")] == ["coorg-signature"]


def test_a_price_change_is_a_new_version_the_old_one_is_kept_and_new_quotes_read_the_new_one(db, w):
    v1 = svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id).id, w.owner.id)
    d2 = svc.create_draft(db, w.t.id, "package", "p", package(rates=[{"label": "Standard", "valid_from": f"{TODAY.year}-01-01",
                          "valid_to": f"{TODAY.year + 1}-12-31", "amount": "21000", "unit": "night"}]), w.mgr.id, note="festival season")
    assert svc.get_effective(db, w.t.id, "package", "p").id == v1.id          # still the old price while the draft waits
    svc.publish(db, w.t.id, d2.id, w.owner.id)
    db.refresh(v1)
    live = svc.get_effective(db, w.t.id, "package", "p")
    assert live.version == 2 and live.data["rates"][0]["amount"] == "21000.00"
    assert v1.status == "superseded" and v1.data["rates"][0]["amount"] == "18000.00"      # history untouched
    assert [r.version for r in svc.history(db, w.t.id, "package", "p")] == [2, 1]
    (ev,) = [a for a in audits(db, w.t.id, "published") if a.payload["version"] == 2]
    assert ev.actor_user_id == w.owner.id and ev.payload["supersedes_version"] == 1
    assert {"path": "rates[0].amount", "old": "18000.00", "new": "21000.00"} in ev.payload["changes"]


def test_a_future_dated_version_waits_and_the_current_one_serves_until_then(db, w):
    v1 = svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id).id, w.owner.id)
    start = TODAY + timedelta(days=10)
    d2 = svc.create_draft(db, w.t.id, "package", "p", package(name="Signature (new season)"), w.owner.id)
    v2 = svc.publish(db, w.t.id, d2.id, w.owner.id, effective_from=start)
    assert svc.get_effective(db, w.t.id, "package", "p").id == v1.id
    assert svc.get_effective(db, w.t.id, "package", "p", at=start - timedelta(days=1)).id == v1.id
    assert svc.get_effective(db, w.t.id, "package", "p", at=start).id == v2.id
    db.refresh(v1)
    assert v1.status == "published" and v1.effective_to == start - timedelta(days=1)       # ends the day before


def test_a_version_cannot_be_published_into_the_past_or_over_a_later_scheduled_one(db, w):
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id).id, w.owner.id)
    far = svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(name="later"), w.owner.id).id, w.owner.id,
                      effective_from=TODAY + timedelta(days=30))
    d = svc.create_draft(db, w.t.id, "package", "p", package(name="in between"), w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id, effective_from=TODAY + timedelta(days=5))
    assert e.value.code == "scheduled_conflict"
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id, effective_from=TODAY - timedelta(days=1))
    assert "past" in e.value.problems[0]
    assert far.status == "published"


def test_a_rejected_draft_is_never_visible_and_cannot_be_published(db, w):
    d = svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id)
    svc.reject(db, w.t.id, d.id, w.owner.id, "wrong price")
    assert svc.get_effective(db, w.t.id, "package", "p") is None
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id)
    assert e.value.code == "not_a_draft"
    assert audits(db, w.t.id, "rejected")[0].payload["reason"] == "wrong price"


def test_publishing_twice_is_refused_and_one_open_draft_per_record(db, w):
    d = svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.create_draft(db, w.t.id, "package", "p", package(name="another"), w.owner.id)
    assert e.value.code == "draft_exists"
    svc.publish(db, w.t.id, d.id, w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id)
    assert e.value.code == "not_a_draft"
    assert len(audits(db, w.t.id, "published")) == 1


def test_a_published_version_cannot_be_edited(db, w):
    d = svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id)
    svc.publish(db, w.t.id, d.id, w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.update_draft(db, w.t.id, d.id, w.owner.id, data=package(name="sneaky"))
    assert e.value.code == "not_a_draft"
    assert svc.get_effective(db, w.t.id, "package", "p").data["name"] == "Signature Caravan - Coorg"


def test_editing_a_draft_keeps_the_live_version_serving_and_audits_the_change(db, w):
    live = svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id).id, w.owner.id)
    d = svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id)
    svc.update_draft(db, w.t.id, d.id, w.owner.id, data=package(max_guests=3))
    assert svc.get_effective(db, w.t.id, "package", "p").id == live.id and svc.get_effective(db, w.t.id, "package", "p").data["max_guests"] == 4
    (ev,) = audits(db, w.t.id, "draft_updated")
    assert {"path": "max_guests", "old": 4, "new": 3} in ev.payload["changes"]


# ─── cross-record rules ───────────────────────────────────────────────────────────────────────────────────

def test_a_package_cannot_be_published_pointing_at_an_unpublished_destination(db, w):
    d = svc.create_draft(db, w.t.id, "package", "p", package(destination_keys=["coorg"]), w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id)
    assert "destination" in e.value.problems[0]
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "destination", "coorg", coorg(), w.owner.id).id, w.owner.id)
    assert svc.publish(db, w.t.id, d.id, w.owner.id).status == "published"


def test_a_destination_in_use_cannot_be_deactivated_and_deactivation_hides_the_record(db, w):
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "destination", "coorg", coorg(), w.owner.id).id, w.owner.id)
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(destination_keys=["coorg"]), w.owner.id).id, w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.deactivate(db, w.t.id, "destination", "coorg", w.owner.id)
    assert e.value.code == "in_use" and "package 'p'" in e.value.problems
    svc.deactivate(db, w.t.id, "package", "p", w.owner.id, "retired")
    assert svc.get_effective(db, w.t.id, "package", "p") is None
    svc.deactivate(db, w.t.id, "destination", "coorg", w.owner.id)
    assert svc.get_effective(db, w.t.id, "destination", "coorg") is None
    assert len(audits(db, w.t.id, "deactivated")) == 2


def test_payment_and_cancellation_terms_cannot_go_live_until_ratha_confirmed_them(db, w):
    pay = {"advance_percent": 30, "balance_due_days_before_checkin": 7}
    d = svc.create_draft(db, w.t.id, "payment_policy", None, pay, w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id)
    assert "not been confirmed" in e.value.problems[0]
    svc.update_draft(db, w.t.id, d.id, w.owner.id, data={**pay, "confirmed_by_ratha": True})
    svc.publish(db, w.t.id, d.id, w.owner.id)
    assert svc.get_effective(db, w.t.id, "payment_policy", "default").data["advance_percent"] == "30.00"


def test_a_reseller_discount_above_the_published_policy_limit_is_refused(db, w):
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "discount_policy", None, {"max_discount_percent": 10}, w.owner.id).id, w.owner.id)
    bad = svc.create_draft(db, w.t.id, "reseller_terms", None, {"tiers": [{"name": "Gold", "commission_percent": 12, "max_discount_percent": 15}]}, w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, bad.id, w.owner.id)
    assert "maximum is 10" in e.value.problems[0]


def test_a_package_larger_than_its_vehicle_is_refused(db, w):
    from app.models.property import Property
    prop = Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Caravan A", slug="a", type="caravan", max_adults=4, max_children=0)
    db.add(prop)
    db.commit()
    d = svc.create_draft(db, w.t.id, "package", "big", package(max_guests=8, vehicle_property_ids=[prop.id]), w.owner.id)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.publish(db, w.t.id, d.id, w.owner.id)
    assert "exceeds the capacity of Caravan A" in e.value.problems[0]


# ─── rollback ─────────────────────────────────────────────────────────────────────────────────────────────

def test_rollback_creates_a_new_version_from_an_old_one_and_never_rewrites_history(db, w):
    v1 = svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id).id, w.owner.id)
    bad = package(rates=[{"label": "Standard", "valid_from": f"{TODAY.year}-01-01", "valid_to": f"{TODAY.year + 1}-12-31", "amount": "1800", "unit": "night"}])
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", bad, w.owner.id).id, w.owner.id)         # a typo: 1800
    assert svc.get_effective(db, w.t.id, "package", "p").data["rates"][0]["amount"] == "1800.00"
    v3 = svc.rollback(db, w.t.id, "package", "p", 1, w.owner.id, publish_now=True)
    assert v3.version == 3 and v3.rollback_of_id == v1.id and v3.status == "published"
    assert svc.get_effective(db, w.t.id, "package", "p").data["rates"][0]["amount"] == "18000.00"
    assert [r.version for r in svc.history(db, w.t.id, "package", "p")] == [3, 2, 1]
    assert svc.history(db, w.t.id, "package", "p")[1].data["rates"][0]["amount"] == "1800.00"                      # the typo stays on record
    assert len(audits(db, w.t.id, "rolled_back")) == 1


def test_rollback_as_a_draft_does_not_change_what_guests_see(db, w):
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id).id, w.owner.id)
    svc.publish(db, w.t.id, svc.create_draft(db, w.t.id, "package", "p", package(name="v2"), w.owner.id).id, w.owner.id)
    d = svc.rollback(db, w.t.id, "package", "p", 1, w.owner.id)
    assert d.status == "draft" and svc.get_effective(db, w.t.id, "package", "p").data["name"] == "v2"
    with pytest.raises(svc.BusinessDataError):
        svc.rollback(db, w.t.id, "package", "p", 99, w.owner.id)


# ─── tenants ──────────────────────────────────────────────────────────────────────────────────────────────

def test_one_tenant_never_reads_or_changes_anothers_records(db, w):
    other = _tenant(db)
    d = svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id)
    svc.publish(db, w.t.id, d.id, w.owner.id)
    assert svc.get_effective(db, other.id, "package", "p") is None and svc.list_effective(db, other.id, "package") == []
    with pytest.raises(svc.BusinessDataError) as e:
        svc.update_draft(db, other.id, d.id, None, data=package())
    assert e.value.status == 404
    with pytest.raises(svc.BusinessDataError):
        svc.reject(db, other.id, d.id, None)
    with pytest.raises(svc.BusinessDataError) as e:
        svc.deactivate(db, other.id, "package", "p", None)
    assert e.value.status == 404
    # the same key in another tenant is a different record with its own versions
    assert svc.create_draft(db, other.id, "package", "p", package(), None).version == 1


# ─── API ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_api_full_cycle_with_permissions_and_draft_isolation(db, client, w):
    owner, ro = _h(w.owner), _h(w.ro)
    r = client.post("/api/v1/business-data/records", json={"kind": "package", "key": "p", "data": package()}, headers=owner)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    # a read-only user can neither write nor see drafts
    assert client.post("/api/v1/business-data/records", json={"kind": "package", "key": "q", "data": package()}, headers=ro).status_code == 403
    assert client.get("/api/v1/business-data/records", headers=ro).status_code == 403
    # draft is not in force
    assert client.get("/api/v1/business-data/effective/package/p", headers=owner).status_code == 404
    assert client.get("/api/v1/business-data/effective/package", headers=owner).json() == []
    v = client.post(f"/api/v1/business-data/records/{rid}/validate", headers=owner).json()
    assert v == {"errors": [], "warnings": []}
    assert client.post(f"/api/v1/business-data/records/{rid}/publish", json={}, headers=owner).status_code == 200
    eff = client.get("/api/v1/business-data/effective/package/p", headers=owner)
    assert eff.status_code == 200 and eff.json()["version"] == 1
    # second version: diff is reachable (route order) and shows the change
    r2 = client.post("/api/v1/business-data/records", json={"kind": "package", "key": "p", "data": package(max_guests=3)}, headers=owner).json()
    d = client.get(f"/api/v1/business-data/records/{r2['id']}/diff", headers=owner).json()
    assert d["against_version"] == 1 and {"path": "max_guests", "old": 4, "new": 3} in d["changes"]
    assert client.post(f"/api/v1/business-data/records/{r2['id']}/reject", json={"reason": "no"}, headers=owner).status_code == 200
    hist = client.get("/api/v1/business-data/records/package/p", headers=owner).json()
    assert [h["status"] for h in hist] == ["rejected", "published"]
    listing = client.get("/api/v1/business-data/records?kind=package", headers=owner).json()
    assert listing[0]["live"]["version"] == 1 and listing[0]["draft"] is None


def test_api_reports_problems_in_plain_language_and_blocks_invalid_publication(db, client, w):
    h = _h(w.owner)
    bad = client.post("/api/v1/business-data/records", json={"kind": "package", "key": "p", "data": package(inclusions=["Meals"], exclusions=["Meals"])}, headers=h)
    assert bad.status_code == 422 and "both included and excluded" in str(bad.json()["detail"]["problems"])
    ref = client.post("/api/v1/business-data/records", json={"kind": "package", "key": "p", "data": package(destination_keys=["nowhere"])}, headers=h).json()
    pub = client.post(f"/api/v1/business-data/records/{ref['id']}/publish", json={}, headers=h)
    assert pub.status_code == 422 and pub.json()["detail"]["code"] == "invalid" and "destination" in str(pub.json()["detail"]["problems"])
    assert client.post("/api/v1/business-data/records", json={"kind": "spaceship", "key": "x", "data": {}}, headers=h).status_code == 422


def test_api_another_tenants_record_id_is_a_404(db, client, w):
    other = _tenant(db)
    rec = svc.create_draft(db, other.id, "package", "p", package(), None)
    db.commit()
    h = _h(w.owner)
    assert client.post(f"/api/v1/business-data/records/{rec.id}/publish", json={}, headers=h).status_code == 404
    assert client.patch(f"/api/v1/business-data/records/{rec.id}", json={"note": "x"}, headers=h).status_code == 404
    assert client.get(f"/api/v1/business-data/records/{rec.id}/diff", headers=h).status_code == 404


def test_api_rollback_endpoint_and_the_kinds_catalogue(db, client, w):
    h = _h(w.owner)
    for name in ("one", "two"):
        rid = client.post("/api/v1/business-data/records", json={"kind": "package", "key": "p", "data": package(name=name)}, headers=h).json()["id"]
        client.post(f"/api/v1/business-data/records/{rid}/publish", json={}, headers=h)
    rb = client.post("/api/v1/business-data/records/package/p/rollback", json={"to_version": 1, "publish": True}, headers=h)
    assert rb.status_code == 200 and rb.json()["version"] == 3
    assert client.get("/api/v1/business-data/effective/package/p", headers=h).json()["data"]["name"] == "one"
    kinds = {k["kind"]: k for k in client.get("/api/v1/business-data/kinds", headers=h).json()}
    assert set(kinds) == {"package", "destination", "itinerary", "reseller_terms", "discount_policy", "stay_rules", "payment_policy", "cancellation_policy"}
    assert kinds["payment_policy"]["singleton"] is True and "properties" in kinds["package"]["schema"]


# ─── PostgreSQL: real concurrency and row-level security ──────────────────────────────────────────────────

from tests.conftest import TestingSessionLocal, engine  # noqa: E402

needs_pg = pytest.mark.skipif(engine.dialect.name != "postgresql", reason="needs real concurrent transactions and RLS (PostgreSQL)")


@needs_pg
def test_two_simultaneous_publishes_of_one_draft_have_exactly_one_winner():
    import threading
    from sqlalchemy import text

    s0 = TestingSessionLocal()
    wk = _workspace(s0)
    d = svc.create_draft(s0, wk.t.id, "package", "race", package(), wk.owner.id)
    s0.commit()
    tid, uid, rid = wk.t.id, wk.owner.id, d.id
    s0.close()
    outcomes, barrier = [], threading.Barrier(2)

    def worker():
        s = TestingSessionLocal()
        try:
            barrier.wait()
            try:
                svc.publish(s, tid, rid, uid)
                s.commit()
                outcomes.append("published")
            except svc.BusinessDataError as exc:
                s.rollback()
                outcomes.append(exc.code)
        finally:
            s.close()

    try:
        ts = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sorted(outcomes) == ["not_a_draft", "published"], outcomes
        chk = TestingSessionLocal()
        assert chk.query(BusinessRecord).filter_by(tenant_id=tid, status="published").count() == 1
        assert chk.query(AuditEvent).filter_by(tenant_id=tid, action="business_record.published").count() == 1
        chk.close()
    finally:
        s = TestingSessionLocal()
        for tbl in ("audit_events", "business_records", "users", "workspace_modules", "role_capabilities"):
            col = "workspace_id" if tbl == "workspace_modules" else "tenant_id"
            s.execute(text(f"DELETE FROM {tbl} WHERE {col} = :t"), {"t": tid})
        s.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        s.commit()
        s.close()


@needs_pg
def test_row_level_security_hides_other_tenants_records_from_the_application_role(db, w):
    """With the tenant context of tenant B set, tenant A's rows are not visible even to an unfiltered query (when the connecting
    role is subject to RLS). The application-level tenant filters are the primary guard; this documents the database layer."""
    from sqlalchemy import text
    other = _tenant(db)
    svc.create_draft(db, w.t.id, "package", "p", package(), w.owner.id)
    db.flush()
    db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": other.id})
    visible = db.execute(text("SELECT count(*) FROM business_records WHERE tenant_id = :t"), {"t": w.t.id}).scalar()
    is_super = db.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar()
    assert visible == 0 or is_super            # a superuser / BYPASSRLS role (like this test container's) is exempt by definition
