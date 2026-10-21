"""Website builder: site creation, draft autosave, approval rules, publish, roles, module gate, tenant isolation."""
import copy

from app.models.module import WorkspaceModule
from app.models.user import UserRole
from app.models.website import SiteDomain, SiteVersion
from tests.test_marketing_studio_content import make_user
from tests.website_fixtures import BASE, add_property, draft, enable, make_tenant, publish_live, save, wsite  # noqa: F401


def test_owner_creates_site_with_seeded_draft_and_free_subdomain(client, db, wsite):
    site = wsite["site"]
    assert site["status"] == "draft" and site["draft"]["number"] == 1 and site["live"] is None
    assert site["settings"]["booking_mode"] == "request"          # nothing is charged until the owner chooses
    sub = [d for d in site["domains"] if d["kind"] == "subdomain"]
    assert len(sub) == 1 and sub[0]["status"] == "active" and sub[0]["hostname"].startswith(wsite["tenant"].slug[:5])
    d = draft(client, wsite["owner_h"])
    keys = {p["key"] for p in d["doc"]["pages"]}
    assert {"home", "contact", "policies", "stays"} <= keys
    assert d["doc"]["site"]["contact"]["phone"] == "+919876543210"
    assert client.post(f"{BASE}/site", json={}, headers=wsite["owner_h"]).status_code == 409


def test_autosave_needs_the_sha_it_was_based_on(client, wsite):
    d = draft(client, wsite["mkt_h"])
    doc = d["doc"]
    doc["pages"][0]["content"][0]["props"]["title"] = "Two villas, one *quiet* valley"
    r = save(client, wsite["mkt_h"], doc, d["version"]["sha256"])
    assert r.status_code == 200 and r.json()["version"]["number"] == 1
    stale = save(client, wsite["owner_h"], doc, d["version"]["sha256"])
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_changed"


def test_marketing_submits_another_approver_publishes(client, db, wsite):
    d = draft(client, wsite["mkt_h"])
    vid = d["version"]["id"]
    assert client.post(f"{BASE}/versions/{vid}/submit", json={"version_id": vid}, headers=wsite["mkt_h"]).status_code == 200
    assert client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["mkt_h"]).status_code == 403
    r = client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["manager_h"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "live" and out["live"]["id"] == vid
    assert db.get(SiteVersion, vid).status == "published"


def test_manager_cannot_publish_what_they_submitted(client, wsite):
    d = draft(client, wsite["manager_h"])
    vid = d["version"]["id"]
    client.post(f"{BASE}/versions/{vid}/submit", json={"version_id": vid}, headers=wsite["manager_h"])
    r = client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["manager_h"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "self_approval"
    assert client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["manager2_h"]).status_code == 200


def test_only_owner_publishes_a_draft_directly(client, wsite):
    d = draft(client, wsite["manager_h"])
    vid = d["version"]["id"]
    r = client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["manager_h"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "approval_required"
    publish_live(client, wsite)


def test_editing_after_submit_makes_a_new_draft_and_withdraws_review(client, db, wsite):
    d = draft(client, wsite["mkt_h"])
    v1 = d["version"]["id"]
    client.post(f"{BASE}/versions/{v1}/submit", json={"version_id": v1}, headers=wsite["mkt_h"])
    doc = d["doc"]
    doc["pages"][0]["content"][0]["props"]["kicker"] = "Pool villas in Coorg"
    r = save(client, wsite["mkt_h"], doc, d["version"]["sha256"])
    assert r.status_code == 200 and r.json()["version"]["number"] == 2 and r.json()["version"]["status"] == "draft"
    assert db.get(SiteVersion, v1).status == "withdrawn"
    assert client.post(f"{BASE}/versions/{v1}/publish", json={"version_id": v1}, headers=wsite["owner_h"]).status_code == 409


def test_publish_is_blocked_without_contact_details(client, wsite):
    d = draft(client, wsite["owner_h"])
    doc = d["doc"]
    doc["site"]["contact"] = {"phone": "", "whatsapp": "", "email": "", "address": ""}
    d2 = save(client, wsite["owner_h"], doc, d["version"]["sha256"]).json()
    r = client.post(f"{BASE}/versions/{d2['version']['id']}/publish", json={"version_id": d2["version"]["id"]}, headers=wsite["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "checks_failed"


def test_validation_drops_unknown_sections_foreign_photos_and_unsafe_links(client, db, wsite):
    d = draft(client, wsite["owner_h"])
    doc = copy.deepcopy(d["doc"])
    home = doc["pages"][0]["content"]
    home.append({"type": "Marquee", "props": {"text": "x"}})
    home[0]["props"]["image1"] = "asset:00000000-0000-0000-0000-000000000000"
    home[0]["props"]["cta_link"] = "javascript:alert(1)"
    home.append({"type": "BookingEngine", "props": {}})          # system section outside its page
    r = save(client, wsite["owner_h"], doc, d["version"]["sha256"])
    assert r.status_code == 200
    out = r.json()
    types = [b["type"] for b in out["doc"]["pages"][0]["content"]]
    assert "Marquee" not in types and "BookingEngine" not in types
    hero = out["doc"]["pages"][0]["content"][0]["props"]
    assert hero["image1"] == "" and hero["cta_link"] == ""
    assert any("photo" in p for p in out["problems"])


def test_reject_sends_back_and_restore_makes_a_new_draft(client, db, wsite):
    d = draft(client, wsite["mkt_h"])
    v1 = d["version"]["id"]
    client.post(f"{BASE}/versions/{v1}/submit", json={"version_id": v1}, headers=wsite["mkt_h"])
    r = client.post(f"{BASE}/versions/{v1}/reject", json={"version_id": v1, "note": "Hero photo first"}, headers=wsite["owner_h"])
    assert r.status_code == 200 and db.get(SiteVersion, v1).status == "rejected"
    r = client.post(f"{BASE}/versions/{v1}/restore", headers=wsite["mkt_h"])
    assert r.status_code == 200 and r.json()["version"]["number"] == 2 and r.json()["version"]["origin"] == "restore"


def test_front_of_house_cannot_open_the_website(client, wsite):
    assert client.get(f"{BASE}/site", headers=wsite["foh_h"]).status_code == 403
    assert client.get(f"{BASE}/draft", headers=wsite["foh_h"]).status_code == 403


def test_module_off_is_refused(client, db, wsite):
    db.query(WorkspaceModule).filter_by(workspace_id=wsite["tenant"].id).delete()
    db.commit()
    from app.core.cache import ctx_bust
    ctx_bust(wsite["tenant"].id)           # the fixture's requests cached the module list
    r = client.get(f"{BASE}/site", headers=wsite["owner_h"])
    assert r.status_code == 403


def test_settings_change_is_owner_or_manager_and_needs_razorpay_to_take_payments(client, wsite):
    body = {**wsite["site"]["settings"], "booking_mode": "instant"}
    assert client.put(f"{BASE}/site/settings", json=body, headers=wsite["mkt_h"]).status_code == 403
    r = client.put(f"{BASE}/site/settings", json=body, headers=wsite["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "razorpay_missing"
    ok = client.put(f"{BASE}/site/settings", json={**wsite["site"]["settings"], "deposit_percent": 40}, headers=wsite["manager_h"])
    assert ok.status_code == 200 and ok.json()["settings"]["deposit_percent"] == 40


def test_other_tenant_sees_nothing_and_cannot_publish(client, db, wsite):
    other = make_tenant(db)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    r = client.get(f"{BASE}/site", headers=other_h)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_site"
    vid = wsite["site"]["draft"]["id"]
    client.post(f"{BASE}/site", json={}, headers=other_h)     # their own site
    assert client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=other_h).status_code == 404
    assert client.get(f"{BASE}/versions/{vid}", headers=other_h).status_code == 404
    assert db.query(SiteVersion).filter_by(id=vid).one().status == "draft"


def test_custom_domain_rules(client, db, wsite):
    r = client.post(f"{BASE}/domains", json={"hostname": "https://www.Coffee-Villas.in/"}, headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    d = next(x for x in r.json()["domains"] if x["kind"] == "custom")
    assert d["hostname"] == "www.coffee-villas.in" and d["status"] == "pending" and d["verify_token"]
    assert client.post(f"{BASE}/domains", json={"hostname": "www.coffee-villas.in"}, headers=wsite["owner_h"]).status_code == 409
    assert client.post(f"{BASE}/domains", json={"hostname": "x.genhaip.site"}, headers=wsite["owner_h"]).status_code == 422
    assert client.post(f"{BASE}/domains", json={"hostname": "evil.example.in"}, headers=wsite["mkt_h"]).status_code == 403
    sub = next(x for x in r.json()["domains"] if x["kind"] == "subdomain")
    assert client.delete(f"{BASE}/domains/{sub['id']}", headers=wsite["owner_h"]).status_code == 422
    other = make_tenant(db, "Rival")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    client.post(f"{BASE}/site", json={}, headers=other_h)
    assert client.post(f"{BASE}/domains", json={"hostname": "www.coffee-villas.in"}, headers=other_h).status_code == 409


def test_domain_verify_goes_active_when_txt_and_cname_match(db, wsite, monkeypatch):
    from app.services import website_domain_service as dom
    from app.services.website_service import require_site
    site = require_site(db, wsite["tenant"].id)
    d = dom.add(db, site, "www.villa-test.in", actor_id=wsite["owner"].id)
    answers = {("_haip-verify.www.villa-test.in", "TXT"): [d.verify_token], ("www.villa-test.in", "CNAME"): [dom.cname_target()]}
    monkeypatch.setattr(dom, "_doh", lambda name, t: answers.get((name, t), []))
    dom.verify(db, d)
    assert d.status == "active" and d.error is None
    assert db.query(SiteDomain).filter_by(hostname="www.villa-test.in").one().status == "active"
