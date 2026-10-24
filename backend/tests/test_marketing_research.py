"""Research analyst (agency phase B): competitors, manual intake, Business Discovery, brief, Facebook OAuth, deletion."""
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.adapters.instagram import business_discovery as bd
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.core.security import create_access_token
from app.models.audit_event import AuditEvent
from app.models.integration import Integration
from app.models.marketing import MarketingCompetitorPost, MarketingCompetitorSnapshot
from app.schemas.marketing_research import CompetitorIn, CompetitorPostIn
from app.services import marketing_ai_service as ai
from app.services import marketing_channel_connections as conns
from app.services import marketing_content_service as svc
from app.services import marketing_meta_token as meta_token
from app.services import marketing_research_service as research
from tests.test_marketing_studio_content import BASE, ws  # noqa: F401  (fixture)

R = f"{BASE}/research"
POST_URL = "https://www.instagram.com/p/AbCdE12345/"


def _fb(db, tid, status="active"):
    integ = Integration(tenant_id=tid, kind="instagram_fb", status=status,
                        credentials_kms_blob=encrypt_credentials({"access_token": "fb-token"}), config={"ig_user_id": "17840"})
    db.add(integ)
    db.commit()
    return integ


DISCOVERED = {"username": "rival", "name": "Rival Stays", "followers_count": 2000, "media_count": 300, "media": [
    {"id": "r1", "caption": "Sunrise reel", "like_count": 180, "comments_count": 20, "timestamp": "2026-10-10T06:00:00+0000",
     "media_type": "VIDEO", "permalink": "https://www.instagram.com/reel/R1aaaaa/"},
    {"id": "r2", "caption": "Room tour", "like_count": 40, "comments_count": 0, "timestamp": "2026-10-03T06:00:00+0000",
     "media_type": "CAROUSEL_ALBUM", "permalink": "https://www.instagram.com/p/R2bbbbb/"},
]}


# ── Competitors + manual intake ─────────────────────────────────────────────────────────────────────────────────────

def test_competitor_list_rules(client, ws):  # noqa: F811
    r = client.post(f"{R}/competitors", json={"handle": "@Rival.Stays"}, headers=ws["mkt_h"])
    assert r.status_code == 201 and r.json()["handle"] == "rival.stays"
    assert client.post(f"{R}/competitors", json={"handle": "rival.stays"}, headers=ws["mkt_h"]).status_code == 409
    assert client.post(f"{R}/competitors", json={"handle": "not a handle!"}, headers=ws["mkt_h"]).status_code == 422
    assert client.get(R, headers=ws["mkt_h"]).json()["competitors"][0]["handle"] == "rival.stays"


def test_manual_post_is_stored_as_text_and_never_fetched(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    comp = research.add_competitor(db, tid, CompetitorIn(handle="rival"), ws["mkt"].id)
    with pytest.raises(ValueError):
        CompetitorPostIn(permalink="https://evil.example.com/p/x")
    with patch("httpx.get", side_effect=AssertionError("must not fetch")), patch("httpx.Client.get", side_effect=AssertionError):
        post = research.add_manual_post(db, tid, comp.id, CompetitorPostIn(permalink=POST_URL, like_count=120, note="villa reel"), ws["mkt"].id)
    assert post.source == "manual" and post.permalink == POST_URL


def test_other_tenant_cannot_touch_competitors(client, db, ws):  # noqa: F811
    from app.models.tenant import Tenant
    import uuid
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    comp = research.add_competitor(db, other.id, CompetitorIn(handle="theirs"), None)
    db.commit()
    r = client.post(f"{R}/competitors/{comp.id}/posts", json={"permalink": POST_URL}, headers=ws["mkt_h"])
    assert r.status_code == 404


# ── Business Discovery adapter ──────────────────────────────────────────────────────────────────────────────────────

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_adapter_reads_public_fields_from_graph_facebook():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        return httpx.Response(200, json={"business_discovery": {**{k: v for k, v in DISCOVERED.items() if k != "media"},
                                                                "media": {"data": DISCOVERED["media"]}}})
    out = bd.discover("tok", "17840", "rival", client=_client(handler))
    assert out["followers_count"] == 2000 and len(out["media"]) == 2
    assert seen["url"].startswith("https://graph.facebook.com/v20.0/17840?") and seen["auth"] == "Bearer tok"
    assert "reach" not in seen["url"] and "tok" not in seen["url"]


@pytest.mark.parametrize("status,body,kind", [
    (400, {"error": {"code": 190, "message": "expired"}}, "bad_token"),
    (400, {"error": {"code": 4, "message": "limit"}}, "rate_limited"),
    (400, {"error": {"code": 110, "message": "Cannot find User"}}, "not_found"),
])
def test_adapter_error_kinds(status, body, kind):
    with pytest.raises(bd.DiscoveryError) as exc:
        bd.discover("tok", "1", "rival", client=_client(lambda r: httpx.Response(status, json=body)))
    assert exc.value.kind == kind


# ── Snapshots, measured brief, AI brief ─────────────────────────────────────────────────────────────────────────────

def test_snapshots_upsert_posts_and_stop_on_refused_token(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    integ = _fb(db, tid)
    research.add_competitor(db, tid, CompetitorIn(handle="rival"), None)
    research.add_competitor(db, tid, CompetitorIn(handle="second"), None)
    db.commit()
    assert research.snapshot_competitors(db, tid, discover=lambda *a: DISCOVERED) == {"done": 2, "failed": 0}
    research.snapshot_competitors(db, tid, discover=lambda *a: DISCOVERED)
    db.commit()
    assert db.query(MarketingCompetitorPost).filter_by(tenant_id=tid, source="api").count() == 4     # 2 per competitor, no dupes

    def refused(*a):
        raise bd.DiscoveryError("expired", "bad_token")
    out = research.snapshot_competitors(db, tid, discover=refused)
    assert out == {"done": 0, "failed": 1} and integ.status == "error"


def test_measured_engagement_and_labels(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _fb(db, tid)
    comp = research.add_competitor(db, tid, CompetitorIn(handle="rival"), None)
    research.snapshot_competitors(db, tid, discover=lambda *a: DISCOVERED)
    research.add_manual_post(db, tid, comp.id, CompetitorPostIn(permalink=POST_URL, like_count=60, comments_count=0), None)
    db.commit()
    c = research.measured(db, tid)["competitors"][0]
    assert c["followers"] == 2000 and c["manual_posts"] == 1 and c["posts_known"] == 3
    assert c["top_posts"][0]["engagement"] == 200 and c["top_posts"][0]["engagement_rate"] == 0.1
    assert c["posts_per_week"] == 1.0 and c["formats"]["VIDEO"] == 1


def test_brief_needs_posts_then_keeps_only_real_example_links(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    comp = research.add_competitor(db, tid, CompetitorIn(handle="rival"), None)
    db.commit()
    brief = research.run_brief(db, ws["tenant"], None)
    assert brief.status == "failed" and "No competitor posts" in brief.error

    research.add_manual_post(db, tid, comp.id, CompetitorPostIn(permalink=POST_URL, like_count=90), None)
    db.commit()
    answer = {"summary": "Reels of mornings win.", "themes": [
        {"name": "Slow mornings", "why_it_works": "Calm, aspirational", "examples": [POST_URL, "https://www.instagram.com/p/MADEUP/"]}]}
    with patch.object(ai, "_call", return_value=(answer, {"model": "m"}, "nvidia")):
        brief = research.run_brief(db, ws["tenant"], None)
    assert brief.status == "ready" and brief.assessment["themes"][0]["examples"] == [POST_URL]
    assert brief.measured["competitors"][0]["handle"] == "rival"


def test_disconnect_deletes_api_data_and_keeps_manual(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    integ = _fb(db, tid)
    comp = research.add_competitor(db, tid, CompetitorIn(handle="rival"), None)
    research.snapshot_competitors(db, tid, discover=lambda *a: DISCOVERED)
    research.add_manual_post(db, tid, comp.id, CompetitorPostIn(permalink=POST_URL), None)
    db.commit()
    out = research.disconnect_fb(db, tid, ws["owner"].id)
    db.commit()
    assert out == {"deleted_snapshots": 1, "deleted_posts": 2}
    assert db.query(MarketingCompetitorPost).filter_by(tenant_id=tid).one().source == "manual"
    assert db.query(MarketingCompetitorSnapshot).filter_by(tenant_id=tid).count() == 0
    assert integ.status == "disconnected" and integ.credentials_kms_blob is None
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="marketing.instagram_fb.disconnected").count() == 1


def test_plan_prompt_includes_research(db, ws):  # noqa: F811
    from app.models.marketing import MarketingPlan, MarketingResearchBrief
    tid = ws["tenant"].id
    db.add(MarketingResearchBrief(tenant_id=tid, measured={}, status="ready", assessment={
        "themes": [{"name": "Slow mornings", "why_it_works": "calm", "examples": []}], "formats": ["REELS"],
        "opportunities": [], "avoid": []}))
    plan = MarketingPlan(tenant_id=tid, period_start="2026-11-01", period_end="2026-11-07", status="pending")
    db.add(plan)
    db.commit()
    with patch.object(ai, "_call", side_effect=ValueError("stop")) as call:
        ai.run_plan(db, tid, plan.id)
    assert "Slow mornings" in call.call_args.args[3] and plan.prompt_version == "marketing-plan-v7"


# ── Facebook OAuth (single-use state) ───────────────────────────────────────────────────────────────────────────────

class FakeRedis:
    def __init__(self):
        self.d = {}

    def setex(self, k, ttl, v):
        self.d[k] = v

    def eval(self, script, n, key):
        return self.d.pop(key, None)


@pytest.fixture()
def fb_env(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.api.v1.endpoints.marketing_research._redis", lambda: fake)
    monkeypatch.setattr("app.core.config.settings.META_APP_ID", "app-1")
    monkeypatch.setattr("app.core.config.settings.META_APP_SECRET", "secret")
    monkeypatch.setattr("app.core.config.settings.API_BASE_URL", "https://api.example.com")
    return fake


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def test_oauth_start_needs_owner_or_manager(client, ws, fb_env):  # noqa: F811
    r = client.get(f"{R}/facebook/oauth-start", params={"token": _token(ws["mkt"])}, follow_redirects=False)
    assert r.status_code == 403
    r = client.get(f"{R}/facebook/oauth-start", params={"token": _token(ws["owner"])}, follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["app-1"] and "instagram_basic" in q["scope"][0]
    assert f"oauth:fb:{q['state'][0]}" in fb_env.d


def test_oauth_callback_connects_once_and_rejects_replay(client, db, ws, fb_env, monkeypatch):  # noqa: F811
    fb_env.d["oauth:fb:nonce1"] = json.dumps({"tenant_id": ws["tenant"].id, "user_id": ws["owner"].id})
    answers = iter([{"access_token": "short"}, {"access_token": "long", "expires_in": 5184000},
                    {"data": [{"name": "Ratha Page", "instagram_business_account": {"id": "17841", "username": "ratha"}}]}])
    monkeypatch.setattr("app.api.v1.endpoints.marketing_research._fb_get", lambda path, params: next(answers))
    r = client.get(f"{R}/facebook/oauth-callback", params={"code": "c", "state": "nonce1"}, follow_redirects=False)
    assert r.status_code == 302 and "fb=connected" in r.headers["location"]
    integ = research.fb_connection(db, ws["tenant"].id)
    assert integ.status == "active" and integ.config["ig_user_id"] == "17841"
    assert decrypt_credentials(integ.credentials_kms_blob)["access_token"] == "long"

    r = client.get(f"{R}/facebook/oauth-callback", params={"code": "c", "state": "nonce1"}, follow_redirects=False)
    assert "fb=error" in r.headers["location"] and "expired" in r.headers["location"]


def test_oauth_callback_without_linked_instagram_fails_cleanly(client, ws, fb_env, monkeypatch):  # noqa: F811
    fb_env.d["oauth:fb:n2"] = json.dumps({"tenant_id": ws["tenant"].id, "user_id": ws["owner"].id})
    answers = iter([{"access_token": "s"}, {"access_token": "l"}, {"data": [{"name": "Page only"}]}])
    monkeypatch.setattr("app.api.v1.endpoints.marketing_research._fb_get", lambda path, params: next(answers))
    r = client.get(f"{R}/facebook/oauth-callback", params={"code": "c", "state": "n2"}, follow_redirects=False)
    assert "fb=error" in r.headers["location"] and "Instagram" in r.headers["location"]


def test_manual_followers_give_an_engagement_rate(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    comp = research.add_competitor(db, tid, CompetitorIn(handle="rival", followers=1000), None)
    research.add_manual_post(db, tid, comp.id, CompetitorPostIn(permalink=POST_URL, like_count=40, comments_count=10), None)
    db.commit()
    c = research.measured(db, tid)["competitors"][0]
    assert (c["followers"], c["followers_source"], c["median_engagement"], c["median_engagement_rate"]) == (1000, "manual", 50, 0.05)


# ── System User token (instead of Facebook Login) ───────────────────────────────────────────────────────────────────

SYS_TOKEN = "EAAsystemusertoken1234567890"
ALL_SCOPES = ["instagram_basic", "instagram_manage_insights", "pages_show_list", "pages_manage_posts",
              "pages_read_engagement", "whatsapp_business_messaging"]


def _meta(scopes=ALL_SCOPES, pages=None, valid=True):
    pages = pages if pages is not None else [
        {"id": "p-other", "name": "Other Page", "access_token": "pt-other"},
        {"id": "p-ratha", "name": "Ratha", "access_token": "pt-ratha",
         "instagram_business_account": {"id": "17841", "username": "rathabyjade"}}]

    def handler(req):
        assert req.url.host == "graph.facebook.com"
        if req.url.path.endswith("/debug_token"):
            return httpx.Response(200, json={"data": {"is_valid": valid, "type": "SYSTEM_USER", "expires_at": 0, "scopes": scopes}})
        return httpx.Response(200, json={"data": pages})
    return _client(handler)


def test_system_token_connects_research_and_page_and_leaves_dm_and_whatsapp_alone(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    ig = Integration(tenant_id=tid, kind="instagram", status="active", config={"instagram_business_account_id": "17841"},
                     credentials_kms_blob=encrypt_credentials({"access_token": "IGAAdm", "instagram_business_account_id": "17841"}))
    wa = Integration(tenant_id=tid, kind="whatsapp_meta", status="active",
                     credentials_kms_blob=encrypt_credentials({"access_token": "EAAwhatsapp"}), config={})
    db.add_all([ig, wa])
    db.commit()
    out = meta_token.connect(db, tid, SYS_TOKEN, ws["owner"].id, http=_meta())
    db.commit()
    assert out["research"] and out["facebook_page"] and out["ig_username"] == "rathabyjade" and out["missing"] == []
    fb = research.fb_connection(db, tid)
    assert fb.status == "active" and fb.config["ig_user_id"] == "17841" and fb.config["source"] == "system_user"
    assert decrypt_credentials(fb.credentials_kms_blob)["access_token"] == SYS_TOKEN
    page = conns.connection(db, tid, conns.FB_KIND)
    assert page.config["page_id"] == "p-ratha"                       # the Page linked to HAIP's Instagram account
    assert decrypt_credentials(page.credentials_kms_blob)["pages"] == {"p-other": "pt-other", "p-ratha": "pt-ratha"}
    assert decrypt_credentials(ig.credentials_kms_blob)["access_token"] == "IGAAdm"
    assert decrypt_credentials(wa.credentials_kms_blob)["access_token"] == "EAAwhatsapp"
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="marketing.meta_token.connected").count() == 1


def test_system_token_without_instagram_permissions_writes_nothing(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    with pytest.raises(svc.MarketingError) as e:
        meta_token.connect(db, tid, SYS_TOKEN, ws["owner"].id, http=_meta(scopes=["pages_show_list", "whatsapp_business_messaging"]))
    assert e.value.code == "missing_permissions" and "instagram_basic" in e.value.problems
    assert research.fb_connection(db, tid) is None and conns.connection(db, tid, conns.FB_KIND) is None


@pytest.mark.parametrize("token,code", [("IGAAinstagramlogintoken123", "instagram_token"), ("not-a-meta-token-at-all", "not_a_token")])
def test_system_token_refuses_other_tokens_before_calling_meta(db, ws, token, code):  # noqa: F811
    boom = _client(lambda r: (_ for _ in ()).throw(AssertionError("must not call Meta")))
    with pytest.raises(svc.MarketingError) as e:
        meta_token.connect(db, ws["tenant"].id, token, ws["owner"].id, http=boom)
    assert e.value.code == code


def test_system_token_with_no_pages_or_invalid_token_fails_cleanly(db, ws):  # noqa: F811
    with pytest.raises(svc.MarketingError) as e:
        meta_token.connect(db, ws["tenant"].id, SYS_TOKEN, ws["owner"].id, http=_meta(pages=[]))
    assert e.value.code == "no_pages"
    with pytest.raises(svc.MarketingError) as e:
        meta_token.connect(db, ws["tenant"].id, SYS_TOKEN, ws["owner"].id, http=_meta(valid=False))
    assert e.value.code == "token_rejected"


def test_system_token_endpoint_is_owner_only_and_stays_in_the_tenant(client, db, ws, monkeypatch):  # noqa: F811
    from app.models.tenant import Tenant
    import uuid
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    real = meta_token.connect
    monkeypatch.setattr(meta_token, "connect", lambda db_, tid, tok, actor, http=None: real(db_, tid, tok, actor, http=_meta()))
    assert client.post(f"{R}/facebook/token", json={"access_token": SYS_TOKEN}, headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{R}/facebook/token", json={"access_token": SYS_TOKEN}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["research"] is True
    assert research.fb_connection(db, ws["tenant"].id).status == "active"
    assert research.fb_connection(db, other.id) is None
    got = client.get(R, headers=ws["owner_h"]).json()["facebook"]
    assert got["status"] == "active" and got["source"] == "system_user"


def test_page_from_system_token_is_available_without_facebook_login(db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.core.config.settings.META_APP_ID", "")
    tid = ws["tenant"].id
    assert conns.status(db, tid)["facebook"]["available"] is False
    meta_token.connect(db, tid, SYS_TOKEN, ws["owner"].id, http=_meta())
    fb = conns.status(db, tid)["facebook"]
    assert fb["available"] is True and fb["connected"] is True and fb["page_name"] == "Ratha"
