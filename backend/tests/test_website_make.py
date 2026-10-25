"""POST /websites/make ("Make my website"): one tap builds a full v2 draft from HAIP data, leaving out sections with nothing
to show, and the new Stays section reads the workspace's own bookable properties."""
from app.services import website_autobuild, website_bindings
from tests.website_fixtures import BASE, add_property, make_tenant, wsite  # noqa: F401


def _types(doc):
    return [s["type"] for s in doc["pages"][0]["sections"]]


def test_make_builds_a_full_draft_with_only_sections_that_have_data(client, db, wsite):  # noqa: F811
    r = client.post(f"{BASE}/make", headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    body = r.json()
    doc = body["doc"]
    assert doc["spec_version"] == 2 and body["version"]["note"] == "Made by HAIP from your data"
    # the fixture has one property and a profile, but no packages, itineraries, photos, reviews or FAQs
    assert _types(doc) == ["hero", "stays", "booking", "booking-cta", "contact"]
    assert doc["pages"][0]["sections"][0]["slots"]["headline"] == "Quiet villas in the coffee hills"
    assert doc["site"]["contact"]["whatsapp"] == "+919876543210"
    assert 50 <= len(doc["pages"][0]["seo"]["description"]) <= 160


def test_stays_section_lists_this_workspaces_bookable_properties_only(client, db, wsite):  # noqa: F811
    add_property(db, wsite["tenant"].id, name="Unassigned overflow")          # placeholder vehicles are never shown
    other = make_tenant(db, "Elsewhere")
    add_property(db, other.id, name="Not mine")
    spec = website_autobuild.spec_for(db, wsite["tenant"])
    items = website_bindings.resolve(db, wsite["tenant"], spec)["bound"]["stays"]["items"]
    assert [i["name"] for i in items] == ["Green Goose"]
    assert items[0]["sleeps"] == 4 and items[0]["summary"] == "A quiet villa in the coffee hills."


def test_make_drops_profile_text_that_states_a_price(client, db, wsite):  # noqa: F811
    t = wsite["tenant"]
    t.brand_config = {"business_profile": {"tagline": "Villas from ₹12,000 a night", "contact_phone": "+919876543210"}}
    db.commit()
    r = client.post(f"{BASE}/make", headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    assert "12,000" not in r.text


def test_make_creates_the_site_when_there_is_none(client, db, tenant_and_user):
    from tests.conftest import seed_capabilities
    from tests.website_fixtures import enable
    t = tenant_and_user["tenant"]
    seed_capabilities(db, t.id)
    enable(db, t.id)
    add_property(db, t.id)
    r = client.post(f"{BASE}/make", headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 201, r.text
    assert r.json()["site"]["url"].startswith("https://")


def test_missing_names_each_left_out_section_with_where_to_fix_it(client, wsite):  # noqa: F811
    r = client.get(f"{BASE}/missing", headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    items = {m["section"]: m for m in r.json()["items"]}
    assert set(items) == {"packages", "itinerary", "gallery", "reviews", "faq"}      # it has a stay, so stays/booking show
    assert items["gallery"]["href"].startswith("/dashboard/") and "photos" in items["gallery"]["how"]


def test_make_needs_website_approve(client, wsite):  # noqa: F811
    assert client.post(f"{BASE}/make", headers=wsite["foh_h"]).status_code == 403
    assert client.post(f"{BASE}/make", headers=wsite["mkt_h"]).status_code == 403
    assert client.post(f"{BASE}/make", headers=wsite["manager_h"]).status_code == 201
