"""Instagram connect: a Facebook token is refused, a real Instagram token is checked, and the account is subscribed to
DM/comment webhooks on connect (manual and OAuth). Jade, 7 Nov: an EAA token was accepted as "active" and no DM ever
arrived."""
from datetime import timedelta
from types import SimpleNamespace

import httpx

from app.adapters.instagram import meta_graph
from app.core.security import create_access_token
from app.models.integration import Integration
from app.models.user import UserRole

URL = "/api/v1/integrations/instagram/connect-key"


def _resp(status, body):
    return SimpleNamespace(status_code=status, content=b"x", json=lambda: body)


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def test_facebook_token_is_refused(client, tenant_and_user, db):
    res = client.post(URL, json={"access_token": "EAAWabc", "app_secret": "s"}, headers=_auth(tenant_and_user))
    assert res.status_code == 400 and "Instagram Login" in res.json()["detail"]
    assert db.query(Integration).filter_by(tenant_id=tenant_and_user["tenant"].id, kind="instagram").first() is None


def test_app_secret_only_stays_pending_without_calling_meta(client, tenant_and_user, db, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Meta call")))
    res = client.post(URL, json={"app_secret": "s"}, headers=_auth(tenant_and_user))
    assert res.status_code == 200 and res.json()["status"] == "pending"


def test_instagram_token_is_checked_and_account_subscribed(client, tenant_and_user, db, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get", lambda url, **k: _resp(200, {"user_id": "1784", "username": "jadehospitainment"}))
    monkeypatch.setattr(httpx, "post", lambda url, **k: calls.append((url, k)) or _resp(200, {"success": True}))
    res = client.post(URL, json={"access_token": "IGAAtok", "app_secret": "s"}, headers=_auth(tenant_and_user))
    assert res.status_code == 200 and res.json()["status"] == "connected" and "warning" not in res.json()
    row = db.query(Integration).filter_by(tenant_id=tenant_and_user["tenant"].id, kind="instagram").one()
    assert row.status == "active" and row.config["webhook_subscribed"] is True
    assert row.config["instagram_business_account_id"] == "1784" and row.config["username"] == "jadehospitainment"
    url, kw = calls[0]
    assert url.endswith("/me/subscribed_apps") and "messages" in kw["data"]["subscribed_fields"]
    assert kw["headers"]["Authorization"] == "Bearer IGAAtok"          # token in the header, never in the URL


def test_bad_instagram_token_is_refused(client, tenant_and_user, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _resp(400, {"error": {"message": "Cannot parse access token"}}))
    res = client.post(URL, json={"access_token": "IGAAbad", "app_secret": "s"}, headers=_auth(tenant_and_user))
    assert res.status_code == 400 and "Cannot parse" in res.json()["detail"]


def test_failed_subscribe_keeps_the_connection_and_warns(client, tenant_and_user, db, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _resp(200, {"user_id": "1784", "username": "j"}))
    monkeypatch.setattr(httpx, "post", lambda url, **k: _resp(400, {"error": {"message": "App not approved"}}))
    res = client.post(URL, json={"access_token": "IGAAtok", "app_secret": "s"}, headers=_auth(tenant_and_user))
    assert res.status_code == 200 and "Webhook subscription" in res.json()["warning"]
    row = db.query(Integration).filter_by(tenant_id=tenant_and_user["tenant"].id, kind="instagram").one()
    assert row.status == "active" and row.config["webhook_subscribed"] is False
    assert row.config["webhook_subscribe_error"] == "App not approved"


def test_subscribe_webhooks_never_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert meta_graph.subscribe_webhooks("t") == (False, "down")


def test_oauth_callback_subscribes_the_account(client, tenant_and_user, db, monkeypatch):
    tid = tenant_and_user["tenant"].id
    client.post(URL, json={"app_secret": "s"}, headers=_auth(tenant_and_user))     # bootstrap, as the UI does
    posted = []

    def fake_post(url, **k):
        posted.append(url)
        if "oauth/access_token" in url:
            return _resp(200, {"access_token": "IGshort", "permissions": "instagram_business_basic"})
        return _resp(200, {"success": True})

    def fake_get(url, **k):
        if url.endswith("/access_token"):
            return _resp(200, {"access_token": "IGAAlong", "expires_in": 5184000})
        return _resp(200, {"user_id": "1784", "username": "jadehospitainment"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)
    state = create_access_token({"tenant_id": tid, "purpose": "ig_oauth"}, expires_delta=timedelta(minutes=5))
    res = client.get("/api/v1/integrations/instagram/oauth-callback", params={"code": "c", "state": state})
    assert res.status_code == 200 and "Instagram connected" in res.text and "Webhook subscription" not in res.text
    assert any(u.endswith("/me/subscribed_apps") for u in posted)
    row = db.query(Integration).filter_by(tenant_id=tid, kind="instagram").one()
    assert row.config["webhook_subscribed"] is True and row.config["token_expires_at"]


def test_wrong_role_cannot_connect(client, tenant_and_user, db):
    user = tenant_and_user["user"]
    user.role = UserRole.FOH if hasattr(UserRole, "FOH") else list(UserRole)[-1]
    db.commit()
    res = client.post(URL, json={"app_secret": "s"}, headers=_auth(tenant_and_user))
    assert res.status_code == 403
