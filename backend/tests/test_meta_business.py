"""Meta Business connection: one System User token, checked with Meta, stored encrypted, used by Ads first."""

import uuid

import pytest

from app.adapters.marketing import meta_ads, meta_business
from app.adapters.marketing.meta_ads import MetaAdsError
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import meta_ads_service
from app.services import meta_business_service as svc

TOKEN = "EAAWtesttoken" + "x" * 40
ALL = [
    "ads_read",
    "leads_retrieval",
    "pages_manage_ads",
    "pages_read_engagement",
    "pages_show_list",
    "instagram_manage_messages",
    "pages_messaging",
]
URL = "/api/v1/meta-business"


def fake_graph(permissions=ALL, accounts=True, pages=True, reject=False):
    def _get(url, params=None):
        if reject:
            raise MetaAdsError("Invalid OAuth access token", status=400, code=190)
        if url.endswith("/me"):
            return {"id": "1", "name": "lead crm"}
        if url.endswith("/me/permissions"):
            return {
                "data": [{"permission": p, "status": "granted"} for p in permissions]
                + [{"permission": "email", "status": "declined"}]
            }
        if url.endswith("/me/adaccounts"):
            return {
                "data": [{"id": "act_42", "name": "Jade Ads", "currency": "INR", "account_status": 1}]
                if accounts
                else []
            }
        if url.endswith("/me/accounts"):
            return {
                "data": [
                    {
                        "id": "147",
                        "name": "Jade Page",
                        "access_token": "PAGE-TOKEN",
                        "instagram_business_account": {"id": "178", "username": "jade"},
                    }
                ]
                if pages
                else []
            }
        raise AssertionError(url)

    return _get


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(meta_ads, "_get", fake_graph())
    monkeypatch.setattr(svc.meta_token_expiry, "fetch_expiry", lambda token: {"valid": True, "expires_at": 0})


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _other(db, role=UserRole.OWNER):
    t = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        name="O",
        email=f"o-{uuid.uuid4().hex[:6]}@test.com",
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


def test_capabilities_say_what_is_missing():
    caps = meta_business.capabilities(
        ["ads_read", "pages_show_list"], [], [{"id": "1", "name": "P", "instagram_id": None}]
    )
    assert caps["ads"] == {"ok": False, "missing": ["no ad account is assigned to this system user"]}
    assert "permission leads_retrieval" in caps["lead_forms"]["missing"] and not caps["lead_forms"]["ok"]
    assert "no Instagram account is linked to a page this token can see" in caps["instagram_dm"]["missing"]
    full = meta_business.capabilities(ALL, [{"id": "act_1"}], [{"id": "1", "name": "P", "instagram_id": "9"}])
    assert all(c["ok"] and not c["missing"] for c in full.values())


def test_connect_checks_stores_encrypted_and_never_returns_the_token(client, db, tenant_and_user, graph):
    tid = tenant_and_user["tenant"].id
    r = client.put(f"{URL}/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] and body["token_name"] == "lead crm" and body["page"] == {"id": "147", "name": "Jade Page"}
    assert all(c["ok"] for c in body["capabilities"].values()) and body["ad_accounts"][0]["id"] == "act_42"
    assert TOKEN not in r.text and "PAGE-TOKEN" not in r.text
    row = db.query(Integration).filter_by(tenant_id=tid, kind="meta_business").one()
    assert TOKEN.encode() not in row.credentials_kms_blob and TOKEN not in str(row.config)
    assert svc.get_token(db, tid) == TOKEN
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="meta_business.connected").one()
    assert TOKEN not in str(ev.payload)
    assert client.get(URL, headers=_h(tenant_and_user)).json()["connected"] is True


def test_rejected_token_is_not_saved(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr(meta_ads, "_get", fake_graph(reject=True))
    r = client.put(f"{URL}/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    assert r.status_code == 400 and "Meta rejected this token" in r.json()["detail"]
    assert db.query(Integration).filter_by(tenant_id=tenant_and_user["tenant"].id, kind="meta_business").first() is None


def test_ads_uses_the_business_token_first_and_whatsapp_still_works(client, db, tenant_and_user, graph):
    tid = tenant_and_user["tenant"].id
    other = _other(db)
    from app.core.encryption import encrypt_credentials

    for t in (tid, other["tenant"].id):  # both have a WhatsApp token, like Ratha
        db.add(
            Integration(
                tenant_id=t,
                kind="whatsapp_meta",
                status="active",
                credentials_kms_blob=encrypt_credentials({"access_token": "WA-TOKEN"}),
            )
        )
    db.commit()
    assert meta_ads_service.get_token(db, tid) == ("WA-TOKEN", "whatsapp")
    client.put(f"{URL}/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    assert meta_ads_service.get_token(db, tid) == (TOKEN, "meta_business")
    assert meta_ads_service.get_token(db, other["tenant"].id) == ("WA-TOKEN", "whatsapp")  # other workspace unchanged
    accounts = client.get("/api/v1/marketing/ads/accounts", headers=_h(tenant_and_user)).json()["accounts"]
    assert [a["id"] for a in accounts] == ["act_42"]


def test_page_choice_recheck_and_disconnect(client, db, tenant_and_user, graph, monkeypatch):
    tid = tenant_and_user["tenant"].id
    client.put(f"{URL}/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    assert client.put(f"{URL}/page", json={"page_id": "999"}, headers=_h(tenant_and_user)).status_code == 422
    assert client.put(f"{URL}/page", json={"page_id": "147"}, headers=_h(tenant_and_user)).json()["page"]["id"] == "147"
    monkeypatch.setattr(meta_ads, "_get", fake_graph(permissions=["ads_read"], pages=False))
    again = client.post(f"{URL}/recheck", headers=_h(tenant_and_user)).json()
    assert again["capabilities"]["lead_forms"]["ok"] is False and again["page"] is None  # page no longer visible
    assert client.delete(URL, headers=_h(tenant_and_user)).json()["connected"] is False
    assert svc.get_token(db, tid) == "" and meta_ads_service.get_token(db, tid) == ("", "")
    assert client.post(f"{URL}/recheck", headers=_h(tenant_and_user)).status_code == 400
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="meta_business.disconnected").count() == 1


def test_wrong_role_and_other_workspace_see_nothing(client, db, tenant_and_user, graph):
    client.put(f"{URL}/token", json={"access_token": TOKEN}, headers=_h(tenant_and_user))
    foh = _other(db, role=UserRole.FOH)
    for call in (
        client.get(URL, headers=_h(foh)),
        client.put(f"{URL}/token", json={"access_token": TOKEN}, headers=_h(foh)),
        client.delete(URL, headers=_h(foh)),
    ):
        assert call.status_code == 403
    stranger = _other(db)
    assert client.get(URL, headers=_h(stranger)).json() == {
        "connected": False,
        "token_name": None,
        "capabilities": None,
        "pages": [],
        "ad_accounts": [],
        "page": None,
        "checked_at": None,
        "token_expires_at": None,
        "lead_forms": {
            "enabled": False,
            "forms": [],
            "last_run_at": None,
            "last_error": None,
            "imported": 0,
            "last_lead_at": None,
        },
        "instagram": {"mode": None, "username": None, "webhook_subscribed": False},
    }
    assert client.delete(URL, headers=_h(stranger)).status_code == 404
    assert svc.get_token(db, tenant_and_user["tenant"].id) == TOKEN


def test_copy_script_moves_an_instagram_facebook_token(db, tenant_and_user, graph, capsys):
    from app.core.encryption import encrypt_credentials
    from scripts.copy_meta_token_to_business import copy_token

    tid = tenant_and_user["tenant"].id
    db.add(
        Integration(
            tenant_id=tid,
            kind="instagram",
            status="active",
            credentials_kms_blob=encrypt_credentials({"access_token": TOKEN, "app_secret": "s"}),
        )
    )
    db.commit()
    assert copy_token(db, tid, apply=False) == "would_copy" and svc.get_token(db, tid) == ""
    assert copy_token(db, tid, apply=True) == "copied" and svc.get_token(db, tid) == TOKEN
    assert copy_token(db, tid, apply=True) == "already_connected"
    assert TOKEN not in capsys.readouterr().out
