"""Website W1: logo (site.brand), floating WhatsApp button (site.whatsapp_button) and own menus (site.menus) on a v2 site."""
import copy
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from app.models.website import SiteVersion
from app.services import website_bindings as binds
from app.services import website_spec_service as wspec
from app.services import website_version_service as vs
from app.services.website_service import WebsiteError
from tests.test_website_spec_v2 import PUB, _photo, spec
from tests.website_fixtures import BASE, host_of, make_tenant, wsite  # noqa: F401

PAGES = [{"slug": "/", "title": "Home", "sections": [
            {"id": "hero", "type": "hero", "variant": "split", "slots": {"headline": "Hello"}},
            {"id": "gallery", "type": "gallery", "variant": "masonry"},
            {"id": "contact", "type": "contact", "variant": "split"}]},
         {"slug": "/journeys", "title": "Journeys", "sections": [{"id": "faq", "type": "faq", "variant": "accordion"}]}]


def w1_spec(**site) -> dict:
    s = spec(pages=copy.deepcopy(PAGES))
    s["site"].update(site)
    return s


def test_a_draft_saved_before_w1_still_passes_the_publish_integrity_check():
    old = wspec.validate(spec())
    assert not {"brand", "whatsapp_button", "menus"} & set(old["site"])     # unset = left out, never stored as null
    assert vs.normalise(old) == old


def test_logo_button_and_menus_round_trip():
    s = w1_spec(brand={"logo": "asset:" + "a" * 8 + "-1111-2222-3333-" + "b" * 12, "show_name": False},
                whatsapp_button={"on": True, "text": "Hi, is the cottage free?"},
                menus={"main": [{"label": "Journeys", "to": "/journeys", "children": [{"label": "FAQ", "to": "/journeys#faq"}]},
                                {"label": "Photos", "to": "/#gallery"}, {"label": "Stay", "to": "/stays/hilltop-villa"}],
                       "footer": [{"label": "Policies", "to": "/policies"}, {"label": "Instagram", "to": "https://instagram.com/x"}]})
    out = wspec.validate(s)
    assert wspec.validate(out) == out
    assert out["site"]["brand"]["show_name"] is False and out["site"]["menus"]["main"][0]["children"][0]["to"] == "/journeys#faq"
    assert out["site"]["menus"]["main"][1]["children"] == []


@pytest.mark.parametrize("site, needle", [
    ({"menus": {"main": [{"label": "Gone", "to": "/rooms"}]}}, "isn't a page on this site"),
    ({"menus": {"main": [{"label": "Gone", "to": "/journeys#reviews"}]}}, "isn't there"),
    ({"menus": {"footer": [{"label": "Plain", "to": "http://example.com"}]}}, "https:// link"),
    ({"menus": {"main": [{"label": "", "to": "/"}]}}, "at least 1 character"),
    ({"brand": {"logo": "https://evil.example/logo.png"}}, "approved library"),
    ({"whatsapp_button": {"on": True, "text": "Stay from ₹4,999 a night"}}, "price was typed"),
])
def test_bad_logo_button_or_menu_is_refused(site, needle):
    with pytest.raises(WebsiteError) as e:
        wspec.validate(w1_spec(**site))
    assert any(needle in p for p in e.value.problems), e.value.problems


def test_a_rebuilt_plan_keeps_menu_links_that_still_fit():
    s = w1_spec(menus={"main": [{"label": "Journeys", "to": "/journeys", "children": [{"label": "FAQ", "to": "/journeys#faq"}]},
                                {"label": "Photos", "to": "/#gallery"}],
                       "footer": [{"label": "Journeys", "to": "/journeys"}, {"label": "Web", "to": "https://example.com"}]})
    s["pages"] = s["pages"][:1]                                       # "Make it again" built only a home page
    s["pages"][0]["sections"] = [x for x in s["pages"][0]["sections"] if x["id"] != "gallery"]
    out = wspec.validate(wspec.prune_menus(s))
    assert out["site"]["menus"] == {"main": [], "footer": [{"label": "Web", "to": "https://example.com"}]}


def test_starter_carries_logo_button_and_menus_and_a_new_site_gets_the_brand_kit_logo():
    tenant = SimpleNamespace(brand_config={"marketing_studio": {"brand_kit": {"logo_asset_id": "1" * 8 + "-2222-3333-4444-" + "5" * 12}}},
                             brand_name="Neelgiri Stays", name="Neelgiri Stays")
    fresh = wspec.starter(tenant)
    assert fresh["site"]["brand"]["logo"].startswith("asset:11111111") and fresh["site"]["whatsapp_button"]["on"] is True
    kept = wspec.starter(tenant, {"name": "N", "whatsapp_button": {"on": False, "text": ""},
                                  "menus": {"main": [{"label": "Journeys", "to": "/journeys"}, {"label": "Old", "to": "/old"}], "footer": []}})
    assert kept["site"]["whatsapp_button"]["on"] is False
    assert [m["label"] for m in kept["site"]["menus"]["main"]] == ["Journeys"]
    wspec.validate(kept)


def test_floating_button_link_only_when_on_with_the_owners_words_and_a_float_code(db, wsite):
    t = wsite["tenant"]
    off = binds.resolve(db, t, wspec.validate(w1_spec()))
    assert off["float_wa"] == {}
    on = binds.resolve(db, t, wspec.validate(w1_spec(whatsapp_button={"on": True, "text": "Hi, is the cottage free?"})))
    home = on["float_wa"]["/"]
    assert home["code"].endswith("-HOME-FLOAT") and on["float_wa"]["/journeys"]["code"].endswith("-JOURNEYS-FLOAT")
    assert unquote(home["href"]).endswith("Hi, is the cottage free? (Ref " + home["code"] + ")")


def test_owner_saves_logo_button_and_menus_and_the_public_site_serves_them(client, db, wsite):
    logo = _photo(db, wsite["tenant"].id)
    d = client.post(f"{BASE}/draft/v2", json={"spec": w1_spec()}, headers=wsite["owner_h"]).json()
    doc = d["doc"]
    doc["site"].update(brand={"logo": f"asset:{logo.id}", "show_name": True}, whatsapp_button={"on": True, "text": ""},
                       menus={"main": [{"label": "Trips", "to": "/journeys", "children": []}], "footer": [{"label": "Home", "to": "/"}]})
    r = client.put(f"{BASE}/draft", json={"doc": doc, "base_sha256": d["version"]["sha256"]}, headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    vid = r.json()["version"]["id"]
    assert client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["owner_h"]).status_code == 200
    boot = client.get(f"{PUB}/{host_of(wsite)}/bootstrap").json()
    assert boot["doc"]["site"]["menus"]["main"][0]["label"] == "Trips"
    assert boot["float_wa"]["/"]["code"].endswith("-HOME-FLOAT")
    assert logo.id in boot["assets"]


def test_a_logo_from_another_workspace_is_removed_not_shown(client, db, wsite):
    other = make_tenant(db, "Elsewhere")
    foreign = _photo(db, other.id)
    d = client.post(f"{BASE}/draft/v2", json={"spec": w1_spec()}, headers=wsite["owner_h"]).json()
    doc = d["doc"]
    doc["site"]["brand"] = {"logo": f"asset:{foreign.id}", "show_name": True}
    r = client.put(f"{BASE}/draft", json={"doc": doc, "base_sha256": d["version"]["sha256"]}, headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    assert r.json()["doc"]["site"]["brand"]["logo"] is None
    stored = db.get(SiteVersion, r.json()["version"]["id"])
    assert vs.normalise(stored.doc) == stored.doc


def test_the_logo_is_never_picked_as_the_hero_or_gallery_photo(db, wsite):
    t = wsite["tenant"]
    photo = _photo(db, t.id)
    logo = _photo(db, t.id)                                            # newest, so it would be picked first
    s = w1_spec(brand={"logo": f"asset:{logo.id}", "show_name": True})
    s["pages"][0]["sections"][0]["variant"] = "split"
    out = binds.resolve(db, t, wspec.validate(s))["bound"]
    assert out["hero"]["media"] == f"asset:{photo.id}"
    assert f"asset:{logo.id}" not in out["gallery"]["media"]
