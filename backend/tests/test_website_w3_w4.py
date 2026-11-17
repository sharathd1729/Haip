"""Website W3 (ask AI about one selected part) and W4 (stay / package page designs, package pages, stay preview)."""
import pytest

from app.models.website import SiteAiJob, SiteVersion
from app.services import website_bindings as binds
from app.services import website_builder_ai as ai
from app.services import website_spec_service as wspec
from app.services import website_version_service as vs
from app.services.website_service import WebsiteError
from tests.test_website_art_director import script  # noqa: F401
from tests.test_website_spec_v2 import PUB, _data, spec
from tests.website_fixtures import BASE, add_property, host_of, make_tenant, wsite  # noqa: F401

B = "/api/v1/websites/builder"
STAY_DESIGN = {"sections": [{"type": "stay-gallery", "variant": "mosaic"}, {"type": "stay-details", "variant": "two-column"},
                            {"type": "reviews", "variant": "grid", "slots": {"heading": "Guests say"}}]}


# ─── W3: the AI may change only the part the owner selected ────────────────────────────────────────────────

def _made(client, wsite):  # noqa: F811
    r = client.post("/api/v1/websites/make", headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    return r.json()["doc"]


def test_a_change_about_one_part_edits_only_that_part(client, db, wsite, script):  # noqa: F811
    doc = _made(client, wsite)
    other = next(s["id"] for s in doc["pages"][0]["sections"] if s["id"] != "hero" and s["type"] != "contact")
    script["queue"].extend([
        {"reply": "Done.", "ops": [{"op": "set_layout", "section_id": other, "value": "x"}]},            # the wrong part
        {"reply": "The top now says Coorg.", "ops": [{"op": "set_text", "section_id": "hero", "field": "headline", "value": "Villas in *Coorg*"}]}])
    r = client.post(f"{B}/change", json={"text": "say Coorg here", "section_id": "hero"}, headers=wsite["owner_h"])
    assert r.status_code == 202, r.text
    job = ai.run(db, wsite["tenant"].id, r.json()["id"])
    db.commit()
    assert job.status == "ready" and job.result["section"] == "hero" and job.result["attempts"] == 2
    new = db.get(SiteVersion, job.result_version_id).doc
    assert new["pages"][0]["sections"][0]["slots"]["headline"] == "Villas in *Coorg*"
    assert "SELECTED SECTION: hero" in str(script["calls"][0])


def test_a_focused_change_may_not_touch_contact_look_or_pages(client, db, wsite, script):  # noqa: F811
    _made(client, wsite)
    bad = {"reply": "Done.", "ops": [{"op": "set_contact", "field": "whatsapp", "value": "+91 98450 22222"}]}
    script["queue"].extend([bad, bad])
    r = client.post(f"{B}/change", json={"text": "change my number", "section_id": "hero"}, headers=wsite["owner_h"])
    job = ai.run(db, wsite["tenant"].id, r.json()["id"])
    db.commit()
    assert job.status == "failed" and "set_contact is not allowed" in job.error


def test_asking_about_a_part_that_is_gone_is_refused(client, wsite):  # noqa: F811
    _made(client, wsite)
    r = client.post(f"{B}/change", json={"text": "make it calmer", "section_id": "nope"}, headers=wsite["owner_h"])
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_section"


def test_another_workspace_cannot_aim_a_change_at_our_parts(client, db, wsite):  # noqa: F811
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user
    _made(client, wsite)
    other = make_tenant(db, "Elsewhere")
    _, oh = make_user(db, other.id, UserRole.OWNER)
    r = client.post(f"{B}/change", json={"text": "make it calmer", "section_id": "hero"}, headers=oh)
    assert r.status_code in (403, 404)
    assert db.query(SiteAiJob).filter_by(tenant_id=wsite["tenant"].id).count() == 0


# ─── W4: page designs ──────────────────────────────────────────────────────────────────────────────────────

def test_designs_validate_get_site_unique_ids_and_old_drafts_stay_intact():
    assert "templates" not in wspec.validate(spec())
    out = wspec.validate(spec(templates={"stay": STAY_DESIGN}))
    assert [s["id"] for s in out["templates"]["stay"]["sections"]] == ["stay-gallery", "stay-details", "reviews"]
    assert "package" not in out["templates"] and vs.normalise(out) == out


@pytest.mark.parametrize("over, needle", [
    ({"templates": {"stay": {"sections": [{"type": "hero", "variant": "split", "slots": {"headline": "x"}}]}}}, "use a 'hero'"),
    ({"templates": {"package": {"sections": [{"type": "stay-map", "variant": "card"}]}}}, "use a 'stay-map'"),
    ({"templates": {"stay": {"sections": [{"id": "packages", "type": "stay-map", "variant": "card"}]}}}, "two sections use the id"),
])
def test_bad_designs_are_refused(over, needle):
    with pytest.raises(WebsiteError) as e:
        wspec.validate(spec(**over))
    assert any(needle in p for p in e.value.problems), e.value.problems


def test_a_design_part_cannot_sit_on_a_normal_page():
    s = spec()
    s["pages"][0]["sections"].append({"type": "stay-booking", "variant": "card"})
    with pytest.raises(WebsiteError) as e:
        wspec.validate(s)
    assert "belongs on the stay page design" in e.value.problems[0]


def test_design_sections_bind_with_their_own_codes_and_packages_get_pages(db, wsite):  # noqa: F811
    t = wsite["tenant"]
    _data(db, t.id)
    out = binds.resolve(db, t, wspec.validate(spec(templates={"stay": STAY_DESIGN})))
    assert out["bound"]["reviews"]["wa"]["code"].endswith("-STAYS-REVIEWS")
    assert out["page_wa"]["/stays"]["code"].endswith("-STAYS-NAV")
    assert [p["key"] for p in out["packages_index"]] == ["coorg-signature"]          # retail + published only
    assert out["packages_index"][0]["wa"]["code"].endswith("-PACKAGES-DETAILS")


def test_menu_links_may_go_to_package_pages():
    s = spec()
    s["site"]["menus"] = {"main": [{"label": "Trip", "to": "/packages/coorg-signature", "children": []}], "footer": []}
    assert wspec.validate(s)["site"]["menus"]["main"][0]["to"] == "/packages/coorg-signature"


def test_published_design_and_package_pages_reach_the_public_site(client, db, wsite):  # noqa: F811
    _data(db, wsite["tenant"].id)
    d = client.post(f"{BASE}/draft/v2", json={"spec": spec(templates={"stay": STAY_DESIGN, "package": {"sections": [
        {"type": "package-details", "variant": "two-column"}]}})}, headers=wsite["owner_h"]).json()
    vid = d["version"]["id"]
    assert client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["owner_h"]).status_code == 200
    boot = client.get(f"{PUB}/{host_of(wsite)}/bootstrap").json()
    assert boot["doc"]["templates"]["stay"]["sections"][0]["type"] == "stay-gallery"
    assert boot["packages_index"][0]["name"] and "price" in boot["packages_index"][0]


def test_stay_preview_for_the_design_editor(client, db, wsite):  # noqa: F811
    p = add_property(db, wsite["tenant"].id, name="Hilltop Villa")
    r = client.get(f"{BASE}/stays/hilltop-villa", headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    assert r.json()["id"] == p.id and r.json()["name"] == "Hilltop Villa"
    assert client.get(f"{BASE}/stays/nowhere", headers=wsite["owner_h"]).status_code == 404


def test_stay_preview_stays_in_the_workspace(client, db, wsite):  # noqa: F811
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user
    add_property(db, wsite["tenant"].id, name="Hilltop Villa")
    other = make_tenant(db, "Elsewhere")
    _, oh = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/stays/hilltop-villa", headers=oh).status_code in (403, 404)


@pytest.mark.parametrize("who", ["foh_h"])
def test_stay_preview_needs_a_website_role(client, db, wsite, who):  # noqa: F811
    add_property(db, wsite["tenant"].id, name="Hilltop Villa")
    assert client.get(f"{BASE}/stays/hilltop-villa", headers=wsite[who]).status_code == 403
