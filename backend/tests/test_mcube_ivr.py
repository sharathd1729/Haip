"""
Tests for the Mcube IVR integration (replacing CallerDesk for Ratha):
  - McubeAdapter.parse_call_webhook (field mapping, HH:MM:SS duration parsing)
  - McubeAdapter.fetch_recording SSRF allowlist (host + S3 bucket path scoping)
  - POST /webhooks/mcube/{tenant_slug}/{url_secret} auth + dispatch
"""
import json
import uuid
import pytest

from app.adapters.ivr.mcube import McubeAdapter
from app.adapters.ivr import get_ivr_adapter
from app.models.tenant import Tenant
from app.models.integration import Integration
from app.core.encryption import encrypt_credentials

_SAMPLE_INBOUND_PAYLOAD = {
    "starttime": "2023-10-12 11:49:57",
    "callid": "80889767291697091597",
    "callto": "8767316316",
    "landingnumber": "8035053336",
    "callfrom": "7816999444",
    "dialstatus": "ANSWER",
    "filename": "https://s3.ap-south-1.amazonaws.com/app.mcube.com/recordings/2023/10/6011/87673163161697091597.wav",
    "calltype": "inbound",
    "endtime": "2023-10-12 11:50:28",
    "duration": "00:00:04",
    "gid": "Integration",
    "agentname": "Test",
    "source": "calltrack",
}


# ── Adapter registration ────────────────────────────────────────────────────

def test_get_ivr_adapter_returns_mcube():
    adapter = get_ivr_adapter("mcube")
    assert isinstance(adapter, McubeAdapter)


# ── parse_call_webhook ──────────────────────────────────────────────────────

def test_parse_call_webhook_maps_fields_correctly():
    adapter = McubeAdapter()
    normalized = adapter.parse_call_webhook(_SAMPLE_INBOUND_PAYLOAD)

    assert normalized.ivr_call_id == "80889767291697091597"
    assert normalized.direction == "inbound"
    assert normalized.from_number == "+917816999444"
    assert normalized.to_number == "+918035053336"
    assert normalized.agent_number == "+918767316316"
    assert normalized.duration_seconds == 4
    assert normalized.recording_url == _SAMPLE_INBOUND_PAYLOAD["filename"]
    assert normalized.provider == "mcube"
    assert normalized.raw == _SAMPLE_INBOUND_PAYLOAD


@pytest.mark.parametrize("raw,expected", [
    ("00:00:04", 4),
    ("00:05:00", 300),
    ("01:00:00", 3600),
    ("1:02:03", 3723),
    ("", 0),
    ("garbage", 0),
    (None, 0),
])
def test_parse_hms_duration(raw, expected):
    assert McubeAdapter._parse_hms_duration(raw) == expected


def test_unanswered_call_duration_is_zero():
    payload = dict(_SAMPLE_INBOUND_PAYLOAD, dialstatus="NoAnswer", duration="00:00:00")
    normalized = McubeAdapter().parse_call_webhook(payload)
    assert normalized.duration_seconds == 0


# ── fetch_recording SSRF allowlist ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_recording_rejects_non_https():
    adapter = McubeAdapter()
    with pytest.raises(ValueError):
        await adapter.fetch_recording("http://s3.ap-south-1.amazonaws.com/app.mcube.com/recordings/x.wav")


@pytest.mark.asyncio
async def test_fetch_recording_rejects_unknown_host():
    adapter = McubeAdapter()
    with pytest.raises(ValueError):
        await adapter.fetch_recording("https://evil.example.com/app.mcube.com/recordings/x.wav")


@pytest.mark.asyncio
async def test_fetch_recording_rejects_arbitrary_bucket_on_shared_s3_host():
    """s3.ap-south-1.amazonaws.com is a generic AWS endpoint -- must be
    scoped to Mcube's own bucket path, not trusted for any bucket."""
    adapter = McubeAdapter()
    with pytest.raises(ValueError):
        await adapter.fetch_recording("https://s3.ap-south-1.amazonaws.com/some-other-bucket/file.wav")


@pytest.mark.asyncio
async def test_fetch_recording_accepts_recordings_mcube_com(monkeypatch):
    """Regression: recordings.mcube.com is Ratha's actual live recording
    host -- every single recording was being permanently rejected (and
    retried 3x before giving up) because this domain was missing from the
    allowlist, discovered live in production. Only asserts the SSRF gate
    passes -- mocks the actual HTTP fetch."""
    import httpx

    class _FakeResponse:
        content = b"fake-audio-bytes"
        def raise_for_status(self): pass

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient())

    adapter = McubeAdapter()
    result = await adapter.fetch_recording("https://recordings.mcube.com/some/path/recording.wav")
    assert result == b"fake-audio-bytes"


# ── Webhook endpoint ─────────────────────────────────────────────────────────

def _connect_mcube(db, tenant_id, webhook_secret="test-mcube-secret", api_key="test-api-key"):
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="mcube", status="active",
        credentials_kms_blob=encrypt_credentials({"api_key": api_key, "webhook_secret": webhook_secret}),
    )
    db.add(integration)
    db.commit()
    return integration


def test_webhook_rejects_unknown_tenant(client):
    res = client.post(
        f"/api/v1/webhooks/mcube/no-such-tenant/whatever",
        content=json.dumps(_SAMPLE_INBOUND_PAYLOAD),
    )
    assert res.status_code == 404


def test_webhook_rejects_wrong_secret(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_mcube(db, tenant.id, webhook_secret="correct-secret")

    res = client.post(
        f"/api/v1/webhooks/mcube/{tenant.slug}/wrong-secret",
        content=json.dumps(_SAMPLE_INBOUND_PAYLOAD),
    )
    assert res.status_code == 401


def test_webhook_rejects_when_not_configured(client, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    res = client.post(
        f"/api/v1/webhooks/mcube/{tenant.slug}/any-secret",
        content=json.dumps(_SAMPLE_INBOUND_PAYLOAD),
    )
    assert res.status_code == 401


def test_webhook_rejects_when_integration_disconnected(client, tenant_and_user, db):
    """Ratha-style disconnect: Integration row + past Call rows stay in the
    DB, but status='disconnected' makes the webhook reject future posts even
    if Mcube's own dashboard is still pointed at this URL."""
    tenant = tenant_and_user["tenant"]
    integration = _connect_mcube(db, tenant.id, webhook_secret="correct-secret")
    integration.status = "disconnected"
    db.commit()

    res = client.post(
        f"/api/v1/webhooks/mcube/{tenant.slug}/correct-secret",
        content=json.dumps(_SAMPLE_INBOUND_PAYLOAD),
    )
    assert res.status_code == 401


def test_webhook_accepts_correct_secret_and_dispatches(client, tenant_and_user, db, monkeypatch):
    tenant = tenant_and_user["tenant"]
    _connect_mcube(db, tenant.id, webhook_secret="correct-secret")

    dispatched = {}

    def fake_delay(**kwargs):
        dispatched.update(kwargs)

    from app.workers.tasks import call_ingest
    monkeypatch.setattr(call_ingest.ingest_call, "delay", fake_delay)

    res = client.post(
        f"/api/v1/webhooks/mcube/{tenant.slug}/correct-secret",
        content=json.dumps(_SAMPLE_INBOUND_PAYLOAD),
    )
    assert res.status_code == 200
    assert dispatched["tenant_id"] == tenant.id
    assert dispatched["ivr_provider"] == "mcube"
    assert dispatched["payload"]["callid"] == "80889767291697091597"


# ── GET /integrations/mcube/webhook-info ────────────────────────────────────

def test_webhook_info_includes_secret_in_url(client, tenant_and_user, db, monkeypatch):
    # Pin the setting: a configured API_BASE_URL (set in .env / prod) wins over the request host.
    monkeypatch.setattr("app.api.v1.endpoints.integrations.settings.API_BASE_URL", "")
    tenant = tenant_and_user["tenant"]
    _connect_mcube(db, tenant.id, webhook_secret="my-secret-123")

    res = client.get(
        "/api/v1/integrations/mcube/webhook-info",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["webhook_url"] == f"https://testserver/api/v1/webhooks/mcube/{tenant.slug}/my-secret-123"


def test_webhook_info_null_url_before_connect(client, tenant_and_user):
    res = client.get(
        "/api/v1/integrations/mcube/webhook-info",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    assert res.json()["webhook_url"] is None


def test_webhook_info_callerdesk_has_no_secret_in_url(client, tenant_and_user, db, monkeypatch):
    """CallerDesk/Acefone still use HMAC signing, not a URL-embedded secret --
    their webhook-info URL should never leak the secret into the path."""
    # Pin the setting: a configured API_BASE_URL (set in .env / prod) wins over the request host.
    monkeypatch.setattr("app.api.v1.endpoints.integrations.settings.API_BASE_URL", "")
    tenant = tenant_and_user["tenant"]
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant.id, kind="callerdesk", status="active",
        credentials_kms_blob=encrypt_credentials({"api_key": "x", "webhook_secret": "cd-secret"}),
    )
    db.add(integration)
    db.commit()

    res = client.get(
        "/api/v1/integrations/callerdesk/webhook-info",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["webhook_url"] == f"https://testserver/api/v1/webhooks/callerdesk/{tenant.slug}"
    assert "cd-secret" not in body["webhook_url"]


def test_webhook_info_uses_configured_public_base_url(client, tenant_and_user, db, monkeypatch):
    """When API_BASE_URL is configured the displayed webhook URL uses it, not the request host."""
    monkeypatch.setattr("app.api.v1.endpoints.integrations.settings.API_BASE_URL", "https://api.example.test/")
    tenant = tenant_and_user["tenant"]
    _connect_mcube(db, tenant.id, webhook_secret="my-secret-123")

    res = client.get(
        "/api/v1/integrations/mcube/webhook-info",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.json()["webhook_url"] == f"https://api.example.test/api/v1/webhooks/mcube/{tenant.slug}/my-secret-123"
