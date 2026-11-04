"""Get found phase S2 (docs/sops/DYNAMIC_SOPS_PLAN.md): OTA listing + promotion SOPs per property, Facebook Page and
TripAdvisor; OTA copy limits read from the platform-rules catalogue; Agoda copy; the calendar-both-ways check; the
discount policy shown only to people who can see revenue; per-property start rules and cross-tenant properties."""

import pytest

from app.models.ical_feed import ICalFeed
from app.models.marketing_partners import MarketingOtaCopy
from app.models.user import UserRole
from app.schemas.marketing_partners import OTA_MODELS, OTA_PLATFORMS, AirbnbCopy, MakeMyTripCopy
from app.schemas.sops import StartIn
from app.services import business_data_service as bds
from app.services import marketing_ai_service as ai
from app.services.sops import catalogue, catalogue_ota, generate, rules
from app.services.sops import service as svc
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, tenant
from tests.test_increment1_defect_specs import _h, _user


@pytest.fixture()
def v(db):
    t = tenant(db)
    t.business_type, t.brand_name = "villa", "Palm Villas"
    p1, p2 = prop(db, t.id, "Villa One"), prop(db, t.id, "Villa Two")
    owner = _user(db, t.id, UserRole.OWNER)
    db.commit()
    return type("V", (), {"t": t, "p1": p1, "p2": p2, "owner": owner})()


def _start(db, v, key, property_id=None, use_ai=False):
    inst = svc.start(db, v.t, StartIn(template_key=key, property_id=property_id), v.owner.id)
    generate.make_version(db, v.t, inst, reason="first", actor_id=v.owner.id, use_ai=use_ai)
    db.commit()
    return inst


def _step(db, v, inst, key):
    return next(s for s in svc.view(db, v.t, inst)["steps"] if s["key"] == key)


def test_ota_copy_limits_are_the_catalogues_numbers():
    assert set(OTA_MODELS) == set(OTA_PLATFORMS) == set(catalogue_ota.OTAS)
    assert AirbnbCopy.model_fields["title"].metadata[-1].max_length == rules.limit("ota.airbnb.title_max")
    assert MakeMyTripCopy.model_fields["about"].metadata[-1].max_length == rules.limit("ota.makemytrip.about_max")
    for p, keys in catalogue_ota.LIMIT_KEYS.items():
        assert all(rules.get(f"ota.{p}.{k}_max") for k in keys)


def test_programmes_come_only_from_the_catalogue_and_are_not_confirmed():
    names = {e.value: e.status for e in rules.all_rules().values() if e.kind == "programme"}
    assert names == {"MMT Black": "unverified", "MMT Biz (business travellers)": "unverified"}


def test_listings_are_offered_per_property_and_only_to_kinds_they_fit(db, v):
    avail = svc.list_view(db, v.t)["available"]
    airbnb = [a for a in avail if a["template_key"] == "airbnb_listing"]
    assert {a["property_name"] for a in airbnb} == {"Villa One", "Villa Two"}
    _start(db, v, "airbnb_listing", v.p1.id)
    airbnb = [a for a in svc.list_view(db, v.t)["available"] if a["template_key"] == "airbnb_listing"]
    assert [a["property_name"] for a in airbnb] == ["Villa Two"]
    assert not catalogue.applies(catalogue.BY_KEY["airbnb_listing"], "caravan")
    assert catalogue.applies(catalogue.BY_KEY["facebook_page"], "caravan")


def test_per_property_start_rules(db, v):
    with pytest.raises(svc.SopError) as e:
        svc.start(db, v.t, StartIn(template_key="booking_listing"), v.owner.id)
    assert e.value.code == "property_needed"
    other = tenant(db)
    foreign = prop(db, other.id, "Not yours")
    with pytest.raises(svc.SopError) as e:
        svc.start(db, v.t, StartIn(template_key="booking_listing", property_id=foreign.id), v.owner.id)
    assert e.value.status == 404
    with pytest.raises(svc.SopError) as e:
        svc.start(db, v.t, StartIn(template_key="facebook_page", property_id=v.p1.id), v.owner.id)
    assert e.value.code == "no_property"


def test_listing_text_comes_from_the_studio_ota_copy(db, v):
    inst = _start(db, v, "airbnb_listing", v.p1.id)
    copy_step = _step(db, v, inst, "copy")
    assert copy_step["needs"][0]["href"] == "/dashboard/marketing/studio?tab=partners"
    assert {r["key"] for r in copy_step["rules"]} >= {"ota.airbnb.title_max", "ota.airbnb.summary_max"}
    db.add(
        MarketingOtaCopy(
            tenant_id=v.t.id,
            property_id=v.p1.id,
            platform="airbnb",
            status="ready",
            body={"copy": {"title": "Pool villa near Nandi Hills", "summary": "Two bedrooms, a pool."}},
        )
    )
    db.flush()
    generate.make_version(db, v.t, inst, reason="manual", actor_id=v.owner.id, use_ai=False)
    vals = {x["label"]: x["text"] for x in _step(db, v, inst, "copy")["values"]}
    assert vals == {"Title": "Pool villa near Nandi Hills", "Summary": "Two bedrooms, a pool."}


def test_calendar_check_needs_the_platforms_own_link_in_haip(db, v):
    inst = _start(db, v, "airbnb_listing", v.p1.id)
    svc.run_checks(db, v.t, inst)
    assert _step(db, v, inst, "calendar")["check_result"]["result"] == "fail"
    feed = ICalFeed(
        tenant_id=v.t.id,
        property_id=v.p1.id,
        name="Airbnb",
        import_url_enc=b"x",
        export_token="t" * 32,
        is_active=True,
        last_status="ok",
    )
    db.add(feed)
    db.flush()
    svc.run_checks(db, v.t, inst)
    cal = _step(db, v, inst, "calendar")
    assert cal["status"] == "done" and cal["done_by"] is None
    feed.last_status, feed.last_error = "error", "404"
    db.flush()
    svc.run_checks(db, v.t, inst)
    assert _step(db, v, inst, "calendar")["status"] == "todo"


def test_promo_steps_use_policy_programmes_and_never_a_figure_in_the_offer(db, v, monkeypatch):
    bds.publish(
        db,
        v.t.id,
        bds.create_draft(
            db, v.t.id, "discount_policy", None, {"max_discount_percent": 15, "max_discount_amount": 10000}, v.owner.id
        ).id,
        v.owner.id,
    )
    monkeypatch.setattr(ai, "_call", lambda *a, **k: ({"offer_text": "Diwali 20% off"}, {"model": "m"}, "nvidia"))
    inst = _start(db, v, "makemytrip_promos", v.p1.id, use_ai=True)
    disc = _step(db, v, inst, "discount")["values"][0]
    assert disc["restricted"] and "15" in disc["text"] and "₹10,000" in disc["text"]
    assert [c["name"] for c in _step(db, v, inst, "programmes")["categories"]][0].startswith("MMT")
    assert _step(db, v, inst, "offer")["values"] == []  # "20%" is a figure: dropped
    assert "offer_text" in (db.get(generate.SopVersion, inst.current_version_id).ai_note or "")
    assert catalogue.BY_KEY["makemytrip_promos"].recurrence == "seasonal"


def test_api_hides_the_discount_policy_without_revenue_access(client, db, v, monkeypatch):
    seed_capabilities(db, v.t.id)
    bds.publish(
        db,
        v.t.id,
        bds.create_draft(db, v.t.id, "discount_policy", None, {"max_discount_percent": 12}, v.owner.id).id,
        v.owner.id,
    )
    inst = _start(db, v, "airbnb_promos", v.p1.id)
    foh, mgr = _user(db, v.t.id, UserRole.FOH), _user(db, v.t.id, UserRole.MANAGER)

    def disc(user):
        steps = client.get(f"/api/v1/sops/{inst.id}", headers=_h(user)).json()["steps"]
        return next(s for s in steps if s["key"] == "discount")["values"][0]

    assert "12" in disc(mgr)["text"]
    assert disc(foh).get("hidden") and "12" not in disc(foh)["text"]
    other = tenant(db)
    other.business_type = "villa"
    seed_capabilities(db, other.id)
    r = client.post(
        "/api/v1/sops",
        json={"template_key": "airbnb_listing", "property_id": v.p1.id},
        headers=_h(_user(db, other.id, UserRole.OWNER)),
    )
    assert r.status_code == 404 and r.json()["detail"]["code"] == "property_not_found"  # another business's villa
