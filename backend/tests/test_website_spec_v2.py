"""Website builder v2 (W1): SiteSpec validation, data bindings, price policy, WhatsApp codes, the v2 draft endpoint and the
public render path. v1 block sites are covered by test_website_builder.py / test_website_booking.py and must stay green."""
import copy
import json
import re
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from app.models.knowledge import KnowledgeEntry
from app.models.marketing import MarketingGuestReview
from app.models.media_asset import MediaAsset
from app.models.website import Site, SiteVersion
from app.schemas.site_spec import catalogue, contrast_problems
from app.services import business_data_service as bds
from app.services import website_bindings as binds
from app.services import website_spec_service as wspec
from app.services.website_service import WebsiteError
from tests.test_business_data import coorg, package
from tests.website_fixtures import BASE, host_of, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"
PRICE_RE = re.compile(r"(₹|\bRs\.?\s?|\bINR\s?)\s*\d")


def spec(**over) -> dict:
    s = {
        "spec_version": 2,
        "site": {"name": "Wander Test", "contact": {"phone": "+91 98450 00000", "whatsapp": "+91 98450 00000", "address": "Madikeri"}},
        "tokens": {"palette": "forest-amber", "display": "fraunces", "body": "figtree"},
        "pages": [{"slug": "/", "title": "Home", "sections": [
            {"id": "hero", "type": "hero", "variant": "split", "slots": {"headline": "Wake up where the *road* ends"}},
            {"id": "packages", "type": "packages", "variant": "cards-3"},
            {"id": "contact", "type": "contact", "variant": "split"}]}],
    }
    s.update(over)
    return s


def every_variant_spec() -> dict:
    sections = [{"id": f"{t}-{v}", "type": t, "variant": v, "slots": {"headline": "Hello"} if t == "hero" else {}}
                for t, sec in catalogue()["sections"].items() for v in sec["variants"]]
    return spec(pages=[{"slug": "/", "title": "Home", "sections": sections[:12]},
                       {"slug": "/more", "title": "More", "sections": sections[12:]}])


# ─── schema ──────────────────────────────────────────────────────────────────────────────────────────────

def test_frontend_has_an_identical_copy_of_the_catalogue():
    front = Path(__file__).resolve().parents[2] / "frontend" / "src" / "site-blocks" / "v2" / "spec.json"
    assert json.loads(front.read_text(encoding="utf-8")) == catalogue(), "copy website_spec_v2.json to frontend/src/site-blocks/v2/spec.json"


def test_valid_spec_normalises_once_and_fills_defaults():
    out = wspec.validate(every_variant_spec())
    assert wspec.validate(out) == out                                    # idempotent: publish re-checks this
    assert out["tokens"]["palette"]["primary"] == "#2F5D46" and out["tokens"]["motion"] == "calm"
    pk = next(s for p in out["pages"] for s in p["sections"] if s["type"] == "packages")
    assert pk["source"] == "business_data:packages" and pk["slots"]["keys"] == []
    assert sum(len(p["sections"]) for p in out["pages"]) == 27          # 9 types x 3 variants


def test_every_preset_palette_passes_wcag_aa():
    for name, p in catalogue()["palettes"].items():
        assert contrast_problems(p) == [], name


@pytest.mark.parametrize("mutate, needle", [
    (lambda s: s["pages"][0]["sections"].append({"type": "carousel", "variant": "x"}), "type"),
    (lambda s: s["pages"][0]["sections"].append({"type": "hero", "variant": "video", "slots": {"headline": "x"}}), "unknown variant"),
    (lambda s: s["pages"][0]["sections"][1].update(source="business_data:destinations"), "reads from"),
    (lambda s: s["tokens"].update(palette={"name": "mine", "ink": "#777777", "surface": "#888888", "primary": "#2F5D46", "accent": "#A8641C"}), "contrast"),
    (lambda s: s["tokens"].update(display="comic-sans"), "unknown display font"),
    (lambda s: s["pages"][0]["sections"][0]["slots"].update(subhead="Only ₹4,500 a night!"), "price"),
    (lambda s: s["pages"][0]["sections"][0]["slots"].update(headline="From Rs 12000 per night"), "price"),
    (lambda s: s["pages"][0]["sections"][0].update(html="<script>"), "Extra inputs"),
    (lambda s: s["pages"][0].update(slug="/Bad Slug"), "slug"),
    (lambda s: s.update(pages=[{**s["pages"][0], "slug": "/about"}]), "home page"),
    (lambda s: s["pages"][0]["sections"][1].update(id="hero"), "id"),
])
def test_bad_specs_are_rejected_not_repaired(mutate, needle):
    s = spec()
    mutate(s)
    with pytest.raises(WebsiteError) as e:
        wspec.validate(s)
    assert e.value.code == "spec_invalid"
    assert any(needle.lower() in p.lower() for p in e.value.problems), e.value.problems


def test_ref_codes_are_deterministic_and_parseable():
    assert binds.ref_code("RT", "/", "hero") == "RT-HOME-HERO"
    assert binds.ref_code("RT", "/journeys/coorg", "packages-2") == "RT-COORG-PACKAGES2"
    assert binds.ref_prefix(spec()) == "WT"
    assert binds.ref_prefix(spec(site={"name": "x", "ref_prefix": "RT"})) == "RT"
    assert re.fullmatch(r"[A-Z]{2,4}-[A-Z0-9]{1,12}-[A-Z0-9]{1,12}", binds.ref_code("WW", "/a-b", "booking-cta"))


# ─── bindings + price policy ─────────────────────────────────────────────────────────────────────────────

WINDOW = {"label": "Standard", "unit": "night"}


def _publish(db, tid, kind, key, data):
    d = bds.create_draft(db, tid, kind, key, data, None)
    return bds.publish(db, tid, d.id, None)


def _photo(db, tid, status="active", tags=None, people_ok=False):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/m/{uuid.uuid4().hex}.jpg", mime_type="image/jpeg",
                   bytes=10, sha256=uuid.uuid4().hex * 2, status=status, alt_text="Caravan at dawn", tags=tags, people_ok=people_ok)
    db.add(a)
    db.commit()
    return a


def _data(db, tid, *, summary="Two nights in the coffee hills."):
    today = bds.tenant_today(db, tid)
    rate = {**WINDOW, "valid_from": today.isoformat(), "valid_to": (today + timedelta(days=700)).isoformat(), "amount": "18000"}
    _publish(db, tid, "destination", "coorg", coorg())
    _publish(db, tid, "package", "coorg-signature", package(destination_keys=["coorg"], rates=[rate], summary=summary))
    _publish(db, tid, "package", "partner-only", package(name="Partner deal", audience="b2b", rates=[rate]))
    bds.create_draft(db, tid, "package", "unpublished", package(name="Draft trip", rates=[rate]), None)
    _publish(db, tid, "itinerary", "coorg-2n", {"name": "Coorg in two nights", "destination_key": "coorg", "nights": 2,
                                                  "package_keys": ["coorg-signature"],
                                                  "days": [{"day": 1, "title": "Into the hills", "stops": ["Bengaluru", "Madikeri"]},
                                                           {"day": 2, "title": "Estate walk", "stops": ["Estate"], "overnight_location": "Madikeri"},
                                                           {"day": 3, "title": "Home", "stops": ["Bengaluru"]}]})
    for q, status, stale in [("Are pets allowed?", "approved", False), ("Unreviewed?", "pending", False), ("Old?", "approved", True)]:
        db.add(KnowledgeEntry(tenant_id=tid, category="faq", question=q, content="Yes, small dogs are welcome.", source="manual",
                              review_status=status, is_active=True, stale_since=_now() if stale else None))
    for name, rating, consent, comment in [("Meera Rao", 5, True, "Waking up by the river was magic."),
                                           ("Kabir S", 5, False, "Not consented."), ("Tara", 3, True, "It was fine.")]:
        db.add(MarketingGuestReview(tenant_id=tid, source="google", external_id=uuid.uuid4().hex, rating=rating, reviewer=name,
                                    comment=comment, reviewed_at="2026-09-12T10:00:00Z",
                                    consent_at=_now() if consent else None))
    db.commit()


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _bound(db, tenant, s=None):
    return binds.resolve(db, tenant, wspec.validate(s or every_variant_spec()))


def test_bindings_read_only_published_approved_consented_data(db, wsite):
    t = wsite["tenant"]
    _data(db, t.id)
    ok = _photo(db, t.id)
    _photo(db, t.id, status="pending_review")                                    # an unapproved AI image
    _photo(db, t.id, tags={"people": True, "description": "guests"})             # people, no consent recorded
    out = _bound(db, t)
    b = out["bound"]
    pk = b["packages-cards-3"]["items"]
    assert [p["key"] for p in pk] == ["coorg-signature"]                        # no b2b, no draft
    assert pk[0]["days"] == ["Into the hills", "Estate walk", "Home"] and pk[0]["destinations"] == ["Coorg"]
    it = b["itinerary-timeline"]["itinerary"]
    assert it["name"] == "Coorg in two nights" and it["days"][1]["overnight"] == "Madikeri"
    assert b["gallery-grid"]["media"] == [f"asset:{ok.id}"] and b["hero-split"]["media"] == f"asset:{ok.id}"
    assert out["asset_ids"] == {ok.id}
    assert [f["q"] for f in b["faq-accordion"]["items"]] == ["Are pets allowed?"]
    reviews = b["reviews-grid"]
    assert [r["name"] for r in reviews["items"]] == ["Meera"] and reviews["count"] == 3
    assert b["hero-split"]["wa"]["code"] == "WT-HOME-HEROSPLIT"
    assert "Ref%20WT-HOME-HEROSPLIT" in b["hero-split"]["wa"]["href"] and b["hero-split"]["wa"]["href"].startswith("https://wa.me/919845000000")


def test_handoff_mode_never_sends_a_price_figure(db, wsite):
    t = wsite["tenant"]
    _data(db, t.id, summary="Two nights in the hills, only Rs 36,000 all in.")     # a hand-typed figure in published data
    out = _bound(db, t)
    assert out["price_mode"] == "handoff"
    item = out["bound"]["packages-cards-3"]["items"][0]
    assert item["price"] is None and item["price_label"] == "Get the price on WhatsApp"
    assert item["summary"] == ""                                                  # the typed price never leaves the server
    assert not PRICE_RE.search(json.dumps(out["bound"], ensure_ascii=False))


def test_grounded_mode_shows_only_the_live_quote(db, wsite):
    from app.services.package_pricing_service import quote
    t = wsite["tenant"]
    t.brand_config = {**(t.brand_config or {}), "price_disclosure": "grounded"}
    db.commit()
    _data(db, t.id, summary="Only Rs 36,000!")
    item = _bound(db, t)["bound"]["packages-cards-3"]["items"][0]
    today = bds.tenant_today(db, t.id)
    ci = today + timedelta(days=binds.SAMPLE_LEAD_DAYS)
    q = quote(db, t.id, "coorg-signature", ci, ci + timedelta(days=2), 2, as_of=today)
    assert q.ok, q.message
    assert item["price"]["amount"] == str(int(q.total)) and "live quote" in item["price"]["label"]
    assert item["price_label"] is None
    assert item["summary"] == ""                                                  # typed figures are blocked in both modes


# ─── endpoint + render path ──────────────────────────────────────────────────────────────────────────────

def test_owner_creates_a_v2_draft_publishes_it_and_the_public_site_serves_v2(client, db, wsite):
    _data(db, wsite["tenant"].id)
    r = client.post(f"{BASE}/draft/v2", json={"seed": "starter"}, headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["doc"]["spec_version"] == 2 and out["version"]["number"] == 2 and out["version"]["origin"] == "seed"
    assert {c["key"] for c in out["checks"]} >= {"contact_details", "contact_section", "data"}
    assert client.get(f"{BASE}/draft", headers=wsite["owner_h"]).json()["doc"]["spec_version"] == 2
    vid = out["version"]["id"]
    pub = client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["owner_h"])
    assert pub.status_code == 200, pub.text
    boot = client.get(f"{PUB}/{host_of(wsite)}/bootstrap").json()
    assert boot["spec_version"] == 2 and boot["theme"]["vars"]["--v-primary"] == "#2F5D46"
    assert boot["bound"]["packages"]["items"][0]["key"] == "coorg-signature"
    assert boot["page_wa"]["/"]["code"].endswith("-HOME-NAV")
    assert not PRICE_RE.search(json.dumps(boot["bound"], ensure_ascii=False))
    # the v1 version is still in the history and can be restored as a new draft
    v1 = db.query(SiteVersion).filter_by(site_id=wsite["site"]["id"], number=1).one()
    back = client.post(f"{BASE}/versions/{v1.id}/restore", headers=wsite["owner_h"])
    assert back.status_code == 200 and "spec_version" not in back.json()["doc"]


def test_hand_written_spec_is_validated(client, wsite):
    bad = spec()
    bad["pages"][0]["sections"][0]["variant"] = "parallax"
    r = client.post(f"{BASE}/draft/v2", json={"spec": bad}, headers=wsite["manager_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "spec_invalid"
    ok = client.post(f"{BASE}/draft/v2", json={"spec": spec()}, headers=wsite["manager_h"])
    assert ok.status_code == 201, ok.text
    assert client.post(f"{BASE}/draft/v2", json={}, headers=wsite["owner_h"]).status_code == 422


@pytest.mark.parametrize("who", ["mkt_h", "foh_h"])
def test_roles_without_website_approve_cannot_create_a_v2_draft(client, wsite, who):
    assert client.post(f"{BASE}/draft/v2", json={"seed": "starter"}, headers=wsite[who]).status_code == 403


def test_v2_draft_stays_inside_the_callers_workspace(client, db, wsite):
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user
    other = make_tenant(db, "Elsewhere")
    _, oh = make_user(db, other.id, UserRole.OWNER)
    r = client.post(f"{BASE}/draft/v2", json={"seed": "starter"}, headers=oh)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_site"
    assert client.post(f"{BASE}/site", json={}, headers=oh).status_code == 201
    assert client.post(f"{BASE}/draft/v2", json={"spec": spec()}, headers=oh).status_code == 201
    mine = db.query(Site).filter_by(id=wsite["site"]["id"]).one()
    assert db.get(SiteVersion, mine.draft_version_id).doc.get("spec_version") is None   # our draft untouched
    assert db.query(SiteVersion).filter_by(site_id=mine.id).count() == 1


def test_ai_developer_refuses_a_v2_draft(client, wsite):
    client.post(f"{BASE}/draft/v2", json={"spec": spec()}, headers=wsite["owner_h"])
    r = client.post(f"{BASE}/ai/edit", json={"message": "make it calmer"}, headers=wsite["owner_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ai_classic_only"


def test_a_bound_gallery_photo_is_served_but_an_unrelated_one_is_not(db, wsite, monkeypatch):
    from app.services import website_public_service as pub
    monkeypatch.setattr("app.services.media_storage.get_presigned_media_url", lambda key, expires_in=0: f"https://cdn.example/{key}")
    t = wsite["tenant"]
    shown = _photo(db, t.id)
    doc = wspec.validate(spec(pages=[{"slug": "/", "title": "Home", "sections": [
        {"type": "gallery", "variant": "grid", "slots": {"limit": 3}}]}]))
    assert pub.media_url(db, t.id, doc, shown.id).startswith("https://cdn.example/")
    with pytest.raises(WebsiteError):
        pub.media_url(db, t.id, copy.deepcopy(spec()), str(uuid.uuid4()))


# ─── the local demo site (scripts/_demo_site.py, called by seed_local_demo.py) ──────────────────────────

def _demo_module():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "_demo_site.py"
    sp = importlib.util.spec_from_file_location("_demo_site", path)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


def test_demo_spec_uses_every_section_variant():
    out = wspec.validate(_demo_module().WANDERWHEEL_SPEC)
    used = {(s["type"], s["variant"]) for p in out["pages"] for s in p["sections"]}
    assert used == {(t, v) for t, sec in catalogue()["sections"].items() for v in sec["variants"]}


def test_demo_seed_builds_and_publishes_the_v2_site(client, db, tenant_and_user):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import _demo_data as D
    t, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    today = bds.tenant_today(db, t.id)
    for d in D.DESTINATIONS:
        _publish(db, t.id, "destination", d["key"], {"name": d["name"], "description": "Demo route.", "distance_km_from_base": d["km"],
                                                      "travel_hours_from_base": d["hours"]})
    for pk in D.PACKAGES:
        _publish(db, t.id, "package", pk["key"], {"name": pk["name"], "product": pk["product"], "min_nights": pk["nights"],
                                                  "max_nights": pk["nights"], "max_guests": 4, "destination_keys": [pk["dest"]],
                                                  "rates": [{"label": "Season", "valid_from": today.isoformat(),
                                                             "valid_to": (today + timedelta(days=365)).isoformat(), "amount": pk["amount"]}]})
    host = _demo_module().seed(db, t, owner)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert boot["spec_version"] == 2 and [p["slug"] for p in boot["doc"]["pages"]] == ["/", "/journeys", "/about"]
    assert boot["bound"]["route"]["itinerary"]["name"] == "Misty Hills Loop"
    assert len(boot["bound"]["faq"]["items"]) == 6 and len(boot["bound"]["words"]["items"]) == 3
    assert boot["bound"]["hero"]["wa"]["code"] == "WW-HOME-HERO"
    assert not PRICE_RE.search(json.dumps(boot["bound"], ensure_ascii=False))
