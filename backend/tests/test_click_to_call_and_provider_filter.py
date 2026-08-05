"""
Tests for:
  - calls.py list_calls / get_call hiding calls from a disconnected IVR
    provider (data stays in DB, just drops out of the dashboard)
  - POST /calls/click-to-call real per-tenant Vobiz wiring
  - migration 064 (Ratha -> Mcube disconnected, Vobiz-only)
"""
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.models.call import Call, CallDirection
from app.core.encryption import encrypt_credentials


def _make_call(db, tenant_id, ivr_provider, ivr_call_id=None):
    call = Call(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ivr_provider=ivr_provider,
        ivr_call_id=ivr_call_id or str(uuid.uuid4()),
        direction=CallDirection.INBOUND,
        from_number="+919876543210",
        to_number="+912271264296",
        duration_seconds=30,
    )
    db.add(call)
    db.commit()
    return call


# ── list_calls / get_call provider filtering ────────────────────────────────

def test_list_calls_hides_calls_from_disconnected_provider(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()

    _make_call(db, tenant.id, "vobiz")
    _make_call(db, tenant.id, "mcube")

    res = client.get(
        "/api/v1/calls",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert all(item["ivr_provider"] == "vobiz" for item in body["items"])


def test_list_calls_shows_everything_when_no_active_provider_set(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = None
    db.commit()

    _make_call(db, tenant.id, "vobiz")
    _make_call(db, tenant.id, "mcube")

    res = client.get(
        "/api/v1/calls",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    assert res.json()["total"] == 2


def test_get_call_404s_for_disconnected_provider_call_but_data_stays_in_db(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()

    mcube_call = _make_call(db, tenant.id, "mcube")

    res = client.get(
        f"/api/v1/calls/{mcube_call.id}",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 404

    # Row is untouched in the DB -- this is a dashboard-visibility filter, not a delete.
    still_there = db.query(Call).filter_by(id=mcube_call.id).first()
    assert still_there is not None
    assert still_there.ivr_provider == "mcube"


def test_get_call_still_works_for_active_provider_call(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()

    vobiz_call = _make_call(db, tenant.id, "vobiz")

    res = client.get(
        f"/api/v1/calls/{vobiz_call.id}",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200


# ── POST /calls/click-to-call (Vobiz) ────────────────────────────────────────

def _connect_vobiz_full(db, tenant_id, **overrides):
    creds = {
        "webhook_secret": "wh-secret", "api_key": "MA123", "api_secret": "tenant-token",
        "forward_number": "+919000000000", "did_number": "+912271264296",
    }
    creds.update(overrides)
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="vobiz", status="active",
        credentials_kms_blob=encrypt_credentials(creds),
    )
    db.add(integration)
    db.commit()
    return integration


def test_click_to_call_requires_ivr_provider_configured(client, tenant_and_user):
    res = client.post(
        "/api/v1/calls/click-to-call",
        json={"guest_number": "+919876543210"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 400


def test_click_to_call_400s_when_vobiz_partially_configured(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()
    # No Integration row at all yet.

    res = client.post(
        "/api/v1/calls/click-to-call",
        json={"guest_number": "+919876543210"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 400


def test_click_to_call_400s_when_did_number_missing(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()
    _connect_vobiz_full(db, tenant.id, did_number="")

    res = client.post(
        "/api/v1/calls/click-to-call",
        json={"guest_number": "+919876543210"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 400
    assert "did_number" in res.json()["detail"]


def test_click_to_call_defaults_agent_number_to_forward_number_and_fires_vobiz(
    client, tenant_and_user, db, monkeypatch
):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()
    _connect_vobiz_full(db, tenant.id)

    from app.core.config import settings
    monkeypatch.setattr(settings, "API_BASE_URL", "https://haip.example.test")

    captured = {}

    async def fake_initiate(self, agent_number, guest_number, *, did_number="", answer_url=""):
        captured["agent_number"] = agent_number
        captured["guest_number"] = guest_number
        captured["did_number"] = did_number
        captured["answer_url"] = answer_url
        return "req-uuid-999"

    from app.adapters.ivr.vobiz import VobizAdapter
    monkeypatch.setattr(VobizAdapter, "initiate_click_to_call", fake_initiate)

    res = client.post(
        "/api/v1/calls/click-to-call",
        json={"guest_number": "+919876543210"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    assert res.json()["provider_call_id"] == "req-uuid-999"
    assert captured["agent_number"] == "+919000000000"  # forward_number default
    assert captured["guest_number"] == "+919876543210"
    assert captured["did_number"] == "+912271264296"
    assert captured["answer_url"].startswith(
        f"https://haip.example.test/api/v1/webhooks/vobiz/{tenant.slug}/wh-secret/outbound-answer"
    )
    assert "guest_number=%2B919876543210" in captured["answer_url"]


def test_click_to_call_honors_explicit_agent_number_override(client, tenant_and_user, db, monkeypatch):
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()
    _connect_vobiz_full(db, tenant.id)

    from app.core.config import settings
    monkeypatch.setattr(settings, "API_BASE_URL", "https://haip.example.test")

    captured = {}

    async def fake_initiate(self, agent_number, guest_number, *, did_number="", answer_url=""):
        captured["agent_number"] = agent_number
        return "req-uuid-1"

    from app.adapters.ivr.vobiz import VobizAdapter
    monkeypatch.setattr(VobizAdapter, "initiate_click_to_call", fake_initiate)

    res = client.post(
        "/api/v1/calls/click-to-call",
        json={"guest_number": "+919876543210", "agent_number": "+919111111111"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    assert captured["agent_number"] == "+919111111111"
