"""Instagram on the Meta Business token (the second way to connect; Instagram Login stays as it was)."""

import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.adapters.instagram.meta_graph import InstagramGraphAdapter
from app.adapters.marketing import meta_ads
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import meta_business_service as biz

TOKEN = "EAAWsystemtoken" + "x" * 40
PAGE_TOKEN = "EAAPAGEtoken" + "y" * 30
SECRET = "fb-app-secret-123"
PERMS = ["instagram_manage_messages", "pages_messaging", "pages_show_list", "ads_read"]
URL = "/api/v1/meta-business/instagram"


def fake_graph(permissions=PERMS, instagram=True):
    def _get(url, params=None):
        if url.endswith("/me"):
            return {"id": "1", "name": "lead crm"}
        if url.endswith("/me/permissions"):
            return {"data": [{"permission": p, "status": "granted"} for p in permissions]}
        if url.endswith("/me/adaccounts"):
            return {"data": []}
        if url.endswith("/me/accounts"):
            page = {"id": "147", "name": "Demo Page", "access_token": PAGE_TOKEN}
            if instagram:
                page["instagram_business_account"] = {"id": "178", "username": "demovillas"}
            return {"data": [page]}
        raise AssertionError(url)

    return _get


class Http:
    """Records httpx.post / httpx.get calls and answers like Meta."""

    def __init__(self):
        self.posts, self.gets = [], []

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return SimpleNamespace(
            status_code=200,
            content=b"x",
            text="",
            json=lambda: {"success": True, "message_id": "mid.1"},
            raise_for_status=lambda: None,
        )

    def get(self, url, **kw):
        self.gets.append((url, kw))
        return SimpleNamespace(
            status_code=200,
            content=b"x",
            text="",
            json=lambda: {"id": "178", "data": []},
            raise_for_status=lambda: None,
        )


@pytest.fixture
def http(monkeypatch):
    h = Http()
    monkeypatch.setattr(httpx, "post", h.post)
    monkeypatch.setattr(httpx, "get", h.get)
    monkeypatch.setattr(meta_ads, "_get", fake_graph())
    monkeypatch.setattr(biz.meta_token_expiry, "fetch_expiry", lambda token: None)
    return h


def _workspace(db, role=UserRole.OWNER):
    t = Tenant(id=str(uuid.uuid4()), name="W", slug=f"w-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("x" * 12),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return {
        "tenant": t,
        "user": u,
        "access_token": create_access_token({"sub": u.id, "tenant_id": t.id, "role": u.role.value}),
    }


def _h(w):
    return {"Authorization": f"Bearer {w['access_token']}"}


def _ig_row(db, tenant_id):
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram").first()


def _instagram_login_row(db, tenant_id, chats=False):
    db.add(
        Integration(
            tenant_id=tenant_id,
            kind="instagram",
            status="active",
            credentials_kms_blob=encrypt_credentials({"access_token": "IGAAlogin", "app_secret": "ig-secret"}),
            config={"instagram_business_account_id": "9001", "username": "viaLogin"},
        )
    )
    if chats:
        g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest")
        db.add(g)
        db.flush()
        db.add(
            Conversation(
                id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, channel=ChannelType.INSTAGRAM, is_open=True
            )
        )
    db.commit()


class _NoClose:
    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def test_adapter_sends_on_the_right_host_for_each_token_type(http):
    InstagramGraphAdapter(PAGE_TOKEN, "178").send_text("igsid-1", "hi")
    InstagramGraphAdapter("IGAAlogin", "9001").send_text("igsid-2", "hi")  # Instagram Login: unchanged
    assert [u for u, _ in http.posts] == [
        "https://graph.facebook.com/v20.0/me/messages",
        "https://graph.instagram.com/v20.0/9001/messages",
    ]
    InstagramGraphAdapter(PAGE_TOKEN, "178").get_user_profile("igsid-1")
    assert http.gets[-1][0] == "https://graph.facebook.com/v20.0/igsid-1"


def test_instagram_runs_on_the_page_token_and_the_page_is_subscribed(client, db, tenant_and_user, http):
    tid = tenant_and_user["tenant"].id
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    r = client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json()["instagram"] == {"mode": "meta_business", "username": "demovillas", "webhook_subscribed": True}
    assert PAGE_TOKEN not in r.text and TOKEN not in r.text and SECRET not in r.text
    row = _ig_row(db, tid)
    creds = decrypt_credentials(row.credentials_kms_blob)
    assert (
        creds["access_token"] == PAGE_TOKEN and creds["app_secret"] == SECRET
    )  # the page's token, not the system user's
    assert row.status == "active" and row.config["auth_mode"] == "meta_business"
    assert row.config["instagram_business_account_id"] == "178" and row.config["page_id"] == "147"
    url, kw = http.posts[0]
    assert (
        url == "https://graph.facebook.com/v20.0/147/subscribed_apps"
        and kw["headers"]["Authorization"] == f"Bearer {PAGE_TOKEN}"
    )
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="instagram.connected").one()
    assert ev.payload["mode"] == "meta_business" and PAGE_TOKEN not in str(ev.payload)

    # the manual form now only replaces the App Secret; the connection stays
    kept = client.post(
        "/api/v1/integrations/instagram/connect-key", json={"app_secret": "rotated-secret"}, headers=_h(tenant_and_user)
    )
    assert kept.status_code == 200 and kept.json()["status"] == "connected"
    db.expire_all()
    row = _ig_row(db, tid)
    creds = decrypt_credentials(row.credentials_kms_blob)
    assert (row.status, row.config["auth_mode"], creds["access_token"], creds["app_secret"]) == (
        "active",
        "meta_business",
        PAGE_TOKEN,
        "rotated-secret",
    )


def test_webhook_is_accepted_and_signature_checked_in_this_mode(client, db, tenant_and_user, http):
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user))
    body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "178",
                    "time": 1,
                    "messaging": [
                        {
                            "sender": {"id": "igsid-9"},
                            "recipient": {"id": "178"},
                            "timestamp": 1,
                            "message": {"mid": f"m-{uuid.uuid4().hex}", "text": "hello"},
                        }
                    ],
                }
            ],
        }
    ).encode()
    good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    queued = []
    with (
        patch("app.core.database.SessionLocal", return_value=_NoClose(db)),
        patch("app.workers.tasks.process_instagram_dm.process_instagram_dm") as task,
    ):
        task.delay = lambda payload: queued.append(payload)
        bad = client.post(
            "/api/v1/webhooks/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=wrong"},
        )
        ok = client.post(
            "/api/v1/webhooks/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": good},
        )
    assert bad.status_code in (401, 403) and ok.status_code == 200
    assert len(queued) == 1 and queued[0]["sender_id"] == "igsid-9"


def test_what_stops_it(client, db, tenant_and_user, http, monkeypatch):
    assert (
        client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user)).status_code == 400
    )  # no Meta Business token
    monkeypatch.setattr(meta_ads, "_get", fake_graph(permissions=["instagram_manage_messages", "pages_show_list"]))
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    r = client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user))
    assert r.status_code == 400 and "pages_messaging" in r.json()["detail"]
    monkeypatch.setattr(meta_ads, "_get", fake_graph(instagram=False))
    client.post("/api/v1/meta-business/recheck", headers=_h(tenant_and_user))
    r = client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user))
    assert r.status_code == 400 and "no Instagram account" in r.json()["detail"]
    assert _ig_row(db, tenant_and_user["tenant"].id) is None


def test_switching_from_instagram_login_is_refused_once_chats_exist(client, db, tenant_and_user, http):
    tid = tenant_and_user["tenant"].id
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    _instagram_login_row(db, tid, chats=True)
    r = client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user))
    assert r.status_code == 409 and "Instagram Login" in r.json()["detail"]
    db.expire_all()
    assert decrypt_credentials(_ig_row(db, tid).credentials_kms_blob)["access_token"] == "IGAAlogin"  # untouched
    assert (
        client.get("/api/v1/meta-business", headers=_h(tenant_and_user)).json()["instagram"]["mode"]
        == "instagram_login"
    )

    other = _workspace(db)  # Instagram Login but no chats yet: may switch
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(other))
    _instagram_login_row(db, other["tenant"].id, chats=False)
    assert client.post(URL, json={"app_secret": SECRET}, headers=_h(other)).status_code == 200

    # and back: Instagram Login is refused once this mode has chats
    g = Guest(id=str(uuid.uuid4()), tenant_id=other["tenant"].id, name="G")
    db.add(g)
    db.flush()
    db.add(
        Conversation(
            id=str(uuid.uuid4()),
            tenant_id=other["tenant"].id,
            guest_id=g.id,
            channel=ChannelType.INSTAGRAM,
            is_open=True,
        )
    )
    db.commit()
    state = create_access_token(
        {"tenant_id": other["tenant"].id, "purpose": "ig_oauth"}, expires_delta=timedelta(minutes=5)
    )
    back = client.get("/api/v1/integrations/instagram/oauth-callback", params={"code": "c", "state": state})
    assert back.status_code == 409 and "Meta Business token" in back.text


def test_wrong_role_and_other_workspace(client, db, tenant_and_user, http):
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    foh = _workspace(db, role=UserRole.FOH)
    assert client.post(URL, json={"app_secret": SECRET}, headers=_h(foh)).status_code == 403
    stranger = _workspace(db)
    assert (
        client.post(URL, json={"app_secret": SECRET}, headers=_h(stranger)).status_code == 400
    )  # their own workspace has no token
    assert _ig_row(db, stranger["tenant"].id) is None and _ig_row(db, tenant_and_user["tenant"].id) is None
    assert client.get("/api/v1/meta-business", headers=_h(stranger)).json()["instagram"] == {
        "mode": None,
        "username": None,
        "webhook_subscribed": False,
    }


def test_health_check_uses_facebooks_host_and_refresh_is_skipped(client, db, tenant_and_user, http, monkeypatch):
    from sqlalchemy.orm import Session as SASession

    from app.workers.tasks import check_meta_credentials, refresh_instagram_token

    tid = tenant_and_user["tenant"].id
    client.put("/api/v1/meta-business/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    client.post(URL, json={"app_secret": SECRET}, headers=_h(tenant_and_user))
    http.gets.clear()
    check_meta_credentials._check_instagram(db, tid)
    assert http.gets[0][0] == "https://graph.facebook.com/v20.0/178"
    check_meta_credentials._check_instagram_dm_access(db, tid)
    url, kw = http.gets[-1]
    assert url == "https://graph.facebook.com/v21.0/me/conversations" and kw["params"]["platform"] == "instagram"
    monkeypatch.setattr(refresh_instagram_token, "SessionLocal", lambda: SASession(bind=db.connection()))
    n = len(http.gets)
    assert refresh_instagram_token.refresh_tenant_token.run(tid)["status"] == "not_applicable" and len(http.gets) == n
