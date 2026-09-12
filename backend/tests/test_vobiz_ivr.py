"""
Tests for the Vobiz IVR integration (recording-only pass, no DTMF menu):
  - VobizAdapter.parse_call_webhook (merged-payload field mapping)
  - VobizAdapter.fetch_recording SSRF allowlist (api.vobiz.ai only)
  - VobizAdapter.verify_vobiz_signature (V3/V2 HMAC, ported from Dograh's
    own VobizProvider — same signature scheme, tests confirm the port is
    byte-for-byte compatible)
  - POST /webhooks/vobiz/{tenant_slug}/{url_secret}/answer + /recording
    auth + dispatch, including the answer->recording cache bridge
"""
import base64
import hashlib
import hmac
import uuid
import pytest

from app.adapters.ivr.vobiz import VobizAdapter
from app.adapters.ivr import get_ivr_adapter
from app.models.integration import Integration
from app.core.encryption import encrypt_credentials

_MERGED_PAYLOAD = {
    "CallUUID": "call-abc-123",
    "From": "+919876543210",
    "To": "+912271264296",
    "Direction": "inbound",
    "RecordUrl": "https://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-1/",
    "RecordingDuration": "42",
    "agent_number": "+919000000000",
    "started_at": "2026-07-26T10:00:00Z",
    "ended_at": "1690000042000",
}


# ── Adapter registration ────────────────────────────────────────────────────

def test_get_ivr_adapter_returns_vobiz():
    adapter = get_ivr_adapter("vobiz")
    assert isinstance(adapter, VobizAdapter)


# ── parse_call_webhook ──────────────────────────────────────────────────────

def test_parse_call_webhook_maps_fields_correctly():
    adapter = VobizAdapter()
    normalized = adapter.parse_call_webhook(_MERGED_PAYLOAD)

    assert normalized.ivr_call_id == "call-abc-123"
    assert normalized.direction == "inbound"
    assert normalized.from_number == "+919876543210"
    assert normalized.to_number == "+912271264296"
    assert normalized.agent_number == "+919000000000"
    assert normalized.duration_seconds == 42
    assert normalized.recording_url == _MERGED_PAYLOAD["RecordUrl"]
    assert normalized.provider == "vobiz"
    assert normalized.raw == _MERGED_PAYLOAD


def test_parse_call_webhook_falls_back_to_recordfile_key():
    payload = dict(_MERGED_PAYLOAD)
    del payload["RecordUrl"]
    payload["RecordFile"] = "https://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-2/"
    normalized = VobizAdapter().parse_call_webhook(payload)
    assert normalized.recording_url == payload["RecordFile"]


def test_parse_call_webhook_normalizes_leading_zero_indian_number():
    payload = dict(_MERGED_PAYLOAD, From="02271264296")
    normalized = VobizAdapter().parse_call_webhook(payload)
    assert normalized.from_number == "+912271264296"


@pytest.mark.parametrize("raw,expected", [("42", 42), ("0", 0), ("", 0), ("garbage", 0), (None, 0)])
def test_parse_int_duration(raw, expected):
    assert VobizAdapter._parse_int(raw) == expected


# ── fetch_recording SSRF allowlist ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_recording_rejects_non_https():
    adapter = VobizAdapter()
    with pytest.raises(ValueError):
        await adapter.fetch_recording("http://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-1/")


@pytest.mark.asyncio
async def test_fetch_recording_rejects_unknown_host():
    adapter = VobizAdapter()
    with pytest.raises(ValueError):
        await adapter.fetch_recording("https://evil.example.com/recording.mp3")


@pytest.mark.asyncio
async def test_fetch_recording_accepts_api_vobiz_ai(monkeypatch):
    class _FakeResponse:
        content = b"fake-audio-bytes"
        def raise_for_status(self): pass

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient())

    adapter = VobizAdapter()
    result = await adapter.fetch_recording("https://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-1/")
    assert result == b"fake-audio-bytes"


@pytest.mark.asyncio
async def test_fetch_recording_accepts_media_vobiz_ai(monkeypatch):
    """Confirmed live: RecordFile/RecordUrl actually point at media.vobiz.ai,
    not api.vobiz.ai as the docs implied -- the allowlist must include it or
    every real recording fetch gets rejected as SSRF."""
    class _FakeResponse:
        content = b"fake-audio-bytes"
        def raise_for_status(self): pass

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient())

    adapter = VobizAdapter()
    result = await adapter.fetch_recording(
        "https://media.vobiz.ai/v1/Account/MA123/Recording/rec-1.mp3"
    )
    assert result == b"fake-audio-bytes"


@pytest.mark.asyncio
async def test_fetch_recording_uses_per_tenant_credentials_in_headers(monkeypatch):
    """Vobiz is the client's own account -- fetch_recording must send THIS
    tenant's auth_id/auth_token, not a shared/global one."""
    captured_headers = {}

    class _FakeResponse:
        content = b"fake-audio-bytes"
        def raise_for_status(self): pass

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, timeout=None, headers=None):
            captured_headers.update(headers or {})
            return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient())

    adapter = VobizAdapter(auth_id="tenant-auth-id", auth_token="tenant-auth-token")
    result = await adapter.fetch_recording("https://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-1/")
    assert result == b"fake-audio-bytes"
    assert captured_headers["X-Auth-ID"] == "tenant-auth-id"
    assert captured_headers["X-Auth-Token"] == "tenant-auth-token"


# ── _to_e164_in double-prefix defense ────────────────────────────────────────

def test_to_e164_in_strips_accidental_double_country_code():
    """Confirmed live on Ratha's prod: a guest number saved as
    "+91917249066854" (real number +917249066854 with an extra "91" baked
    into the local part by an upstream ingestion bug) got dialed literally,
    instantly rejected by Vobiz (RecordingDurationMs ~20)."""
    from app.api.v1.endpoints.webhooks_vobiz import _to_e164_in
    assert _to_e164_in("+91917249066854") == "+917249066854"


def test_to_e164_in_leaves_normal_e164_number_untouched():
    from app.api.v1.endpoints.webhooks_vobiz import _to_e164_in
    assert _to_e164_in("+917249066854") == "+917249066854"


def test_to_e164_in_normalizes_domestic_format():
    from app.api.v1.endpoints.webhooks_vobiz import _to_e164_in
    assert _to_e164_in("07249066854") == "+917249066854"


def test_to_e164_in_does_not_mangle_a_genuine_12_digit_non_91_local_part():
    """Only the exact double-prefix shape (12 digits starting with '91')
    triggers the strip -- a real 12-digit local part not starting with '91'
    (however unlikely) must pass through unchanged."""
    from app.api.v1.endpoints.webhooks_vobiz import _to_e164_in
    assert _to_e164_in("+91827249066854") == "+91827249066854"


# ── initiate_click_to_call ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initiate_click_to_call_requires_did_number_and_answer_url():
    adapter = VobizAdapter(auth_id="MA123", auth_token="tok")
    with pytest.raises(ValueError):
        await adapter.initiate_click_to_call("+919000000000", "+919876543210")


@pytest.mark.asyncio
async def test_initiate_click_to_call_requires_credentials():
    adapter = VobizAdapter()  # no auth_id/auth_token
    with pytest.raises(ValueError):
        await adapter.initiate_click_to_call(
            "+919000000000", "+919876543210",
            did_number="+912271264296", answer_url="https://example.test/answer",
        )


@pytest.mark.asyncio
async def test_initiate_click_to_call_posts_expected_fields_and_returns_call_id(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"request_uuid": "req-uuid-123", "message": "call fired"}

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, auth=None, data=None, timeout=None):
            captured["url"] = url
            captured["auth"] = auth
            captured["data"] = data
            return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient())

    adapter = VobizAdapter(auth_id="MA123", auth_token="tenant-token")
    call_id = await adapter.initiate_click_to_call(
        "+919000000000", "+919876543210",
        did_number="+912271264296", answer_url="https://example.test/outbound-answer?guest_number=%2B919876543210",
    )
    assert call_id == "req-uuid-123"
    assert captured["url"] == "https://api.vobiz.ai/api/v1/Account/MA123/Call/"
    assert captured["auth"] == ("MA123", "tenant-token")
    assert captured["data"]["from"] == "+912271264296"
    assert captured["data"]["to"] == "+919000000000"
    assert captured["data"]["answer_url"].startswith("https://example.test/outbound-answer")


@pytest.mark.asyncio
async def test_initiate_click_to_call_raises_on_unrecognized_response(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"message": "ok"}  # no recognizable call-id field

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient())

    adapter = VobizAdapter(auth_id="MA123", auth_token="tok")
    with pytest.raises(ValueError):
        await adapter.initiate_click_to_call(
            "+919000000000", "+919876543210",
            did_number="+912271264296", answer_url="https://example.test/answer",
        )


# ── outbound-answer webhook ──────────────────────────────────────────────────

def test_outbound_answer_webhook_requires_guest_number(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/outbound-answer",
        data={"CallUUID": "call-out-1"},
    )
    assert res.status_code == 422  # missing required query param


def test_outbound_answer_webhook_returns_dial_xml_to_guest(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(
        db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000",
    )
    # did_number isn't in the _connect_vobiz helper's default creds -- set directly.
    from app.core.encryption import get_credential, encrypt_credentials
    integration = db.query(Integration).filter_by(tenant_id=tenant.id, kind="vobiz").first()
    integration.credentials_kms_blob = encrypt_credentials({
        "webhook_secret": "correct-secret", "api_key": "MA123", "api_secret": "tok",
        "forward_number": "+919000000000", "did_number": "+912271264296",
    })
    db.commit()

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/outbound-answer"
        "?guest_number=%2B919876543210",
        data={"CallUUID": "call-out-1"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert "<Record" in res.text
    assert 'callerId="+912271264296"' in res.text
    assert "<Number>+919876543210</Number>" in res.text
    assert f"/webhooks/vobiz/{tenant.slug}/correct-secret/recording" in res.text


def test_outbound_answer_webhook_repairs_double_prefixed_guest_number(client, tenant_and_user, db):
    """Regression for the exact bug hit live on Ratha: a stored guest number
    with an accidental double country-code prefix must still get dialed as
    the real 10-digit number, not the malformed one."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")
    from app.core.encryption import encrypt_credentials
    integration = db.query(Integration).filter_by(tenant_id=tenant.id, kind="vobiz").first()
    integration.credentials_kms_blob = encrypt_credentials({
        "webhook_secret": "correct-secret", "api_key": "MA123", "api_secret": "tok",
        "forward_number": "+919000000000", "did_number": "+912271264296",
    })
    db.commit()

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/outbound-answer"
        "?guest_number=%2B91917249066854",
        data={"CallUUID": "call-out-2"},
    )
    assert res.status_code == 200
    assert "<Number>+917249066854</Number>" in res.text
    assert "+91917249066854" not in res.text


def test_outbound_answer_webhook_requires_call_uuid(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/outbound-answer"
        "?guest_number=%2B919876543210",
        data={},
    )
    assert res.status_code == 400


# ── verify_vobiz_signature (ported HMAC scheme) ──────────────────────────────

def test_verify_vobiz_signature_v3_accepts_valid_signature_and_strips_query():
    auth_token = "vobiz-auth-token"
    url = "https://example.test/api/v1/webhooks/vobiz/acme/secret/recording"
    nonce = "12345678901234567890"
    signed_payload = f"{url}.{nonce}"
    signature = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")

    assert VobizAdapter.verify_vobiz_signature(
        url + "?foo=bar",
        {"x-vobiz-signature-v3": signature, "x-vobiz-signature-v3-nonce": nonce},
        auth_token,
    )


def test_verify_vobiz_signature_v2_accepts_valid_signature():
    auth_token = "vobiz-auth-token"
    url = "https://example.test/api/v1/webhooks/vobiz/acme/secret/recording"
    nonce = "12345678901234567890"
    signature = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), f"{url}{nonce}".encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")

    assert VobizAdapter.verify_vobiz_signature(
        url,
        {"X-Vobiz-Signature-V2": signature, "X-Vobiz-Signature-V2-Nonce": nonce},
        auth_token,
    )


def test_verify_vobiz_signature_rejects_missing_signature():
    assert not VobizAdapter.verify_vobiz_signature(
        "https://example.test/whatever", {}, "some-token"
    )


def test_verify_vobiz_signature_rejects_wrong_token():
    url = "https://example.test/whatever"
    nonce = "12345678901234567890"
    signature = base64.b64encode(
        hmac.new(b"correct-token", f"{url}.{nonce}".encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")

    assert not VobizAdapter.verify_vobiz_signature(
        url,
        {"x-vobiz-signature-v3": signature, "x-vobiz-signature-v3-nonce": nonce},
        "wrong-token",
    )


# ── Webhook endpoints ────────────────────────────────────────────────────────

def _connect_vobiz(db, tenant_id, webhook_secret="test-vobiz-secret", forward_number=None,
                    auth_id="MA123", auth_token="vobiz-auth-token"):
    creds = {"webhook_secret": webhook_secret, "api_key": auth_id, "api_secret": auth_token}
    if forward_number:
        creds["forward_number"] = forward_number
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="vobiz", status="active",
        credentials_kms_blob=encrypt_credentials(creds),
    )
    db.add(integration)
    db.commit()
    return integration


def test_answer_webhook_rejects_unknown_tenant(client):
    res = client.post(
        "/api/v1/webhooks/vobiz/no-such-tenant/whatever/answer",
        data={"CallUUID": "x"},
    )
    assert res.status_code == 404


def test_answer_webhook_rejects_wrong_secret(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/wrong-secret/answer",
        data={"CallUUID": "x"},
    )
    assert res.status_code == 401


def test_answer_webhook_rejects_when_not_configured(client, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/any-secret/answer",
        data={"CallUUID": "x"},
    )
    assert res.status_code == 401


def test_answer_webhook_returns_xml_with_record_and_dial(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/answer",
        data={"CallUUID": "call-abc-123", "From": "+919876543210", "To": "+912271264296", "Direction": "inbound"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert "<Record" in res.text
    assert 'recordSession="true"' in res.text
    assert "<Number>+919000000000</Number>" in res.text
    assert f"/webhooks/vobiz/{tenant.slug}/correct-secret/recording" in res.text


def test_answer_webhook_parallel_dial_dedupes_agents_sharing_a_phone_number(client, tenant_and_user, db):
    """Confirmed live on Ratha: parallel ring went completely silent both
    ways while every single-number strategy kept working. Root cause --
    _get_eligible_agents() has no phone dedup, so two agents sharing/
    reusing one number collapsed into two sibling <Number> tags in the same
    <Dial>, dialing one physical handset twice at once. Only the parallel
    path (2+ <Number> tags in one <Dial>) can ever expose this; every other
    strategy resolves to a single number."""
    from app.models.user import User, UserRole

    tenant = tenant_and_user["tenant"]
    tenant.ivr_routing_strategy = "parallel"
    db.add(tenant)

    for name in ("Agent One", "Agent Two"):
        db.add(User(
            id=str(uuid.uuid4()), tenant_id=tenant.id, name=name,
            email=f"{name.lower().replace(' ', '')}@test.com",
            role=UserRole.CONCIERGE, is_active=True,
            phone="+919876500001", ivr_call_routing_enabled=True,
        ))
    db.commit()

    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/answer",
        data={"CallUUID": "call-dup-1", "From": "+919876543210", "To": "+912271264296", "Direction": "inbound"},
    )
    assert res.status_code == 200
    assert res.text.count("<Number>+919876500001</Number>") == 1


def test_answer_webhook_normalizes_double_prefixed_from_number_before_caching(client, tenant_and_user, db):
    """Confirmed live on Ratha: Vobiz's own "From" for some inbound calls
    arrives with a duplicated "91" baked in (a real 7249066854 shows up as
    "917249066854"). _to_e164_in()'s dedup fix already existed and was
    already tested directly, but this cache write -- the only place the
    guest's raw number gets captured for an inbound call -- stored it
    verbatim, so the malformed number is what became Call.from_number (and
    from there, the guest's own phone identity) even after that fix
    shipped. 7 real guests on Ratha had this corruption before it was
    caught and backfilled."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/answer",
        data={"CallUUID": "call-abc-123", "From": "+91917249066854", "To": "+912271264296", "Direction": "inbound"},
    )
    assert res.status_code == 200

    from app.api.v1.endpoints.webhooks_vobiz import _cache_key
    from app.core.cache import get_cached
    cached = get_cached(_cache_key(tenant.id, "call-abc-123"))
    assert cached["From"] == "+917249066854"


def test_answer_webhook_dial_sets_both_callbackurl_and_action(client, tenant_and_user, db):
    """Confirmed live against vobiz.ai/docs/xml/dial: DialAnswer/
    DialConnected (with DialBLegTo) go to callbackUrl, but the terminal
    DialStatus result -- what is_missed_call() actually depends on -- goes
    to a separate `action` attribute. Missing `action` was the real reason
    Call.ivr_dial_status sat NULL on every single call in production."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/answer",
        data={"CallUUID": "call-abc-123", "From": "+919876543210", "To": "+912271264296", "Direction": "inbound"},
    )
    assert res.status_code == 200
    base = f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret"
    # Real-time B-leg events still go to dial-status; the terminal result now
    # goes to dial-action, which returns the XML that replaces the remaining
    # verbs (see the voicemail-after-a-good-call fix).
    assert f'callbackUrl="' in res.text and f"{base}/dial-status" in res.text
    assert f'action="' in res.text and f"{base}/dial-action" in res.text


def test_answer_xml_no_longer_queues_voicemail_after_the_dial(client, tenant_and_user, db, monkeypatch):
    """The voicemail-after-a-good-call bug: with redirect="false" the verb
    after <Dial> ran on EVERY fall-through, including a completed
    conversation (the agent hangs up first, so the guest's leg is still up).
    Guests heard "Sorry we couldn't take your call" right after talking to
    an agent. The simultaneous <Dial> now uses redirect="true" and lets the
    dial-action handler decide, so no voicemail is queued up front."""
    from app.services import ivr_routing_service

    monkeypatch.setattr(ivr_routing_service, "resolve_voicemail_url", lambda t, **kw: "https://x/vm.mp3")

    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/answer",
        data={"CallUUID": "call-vm-1", "From": "+919876543210", "To": "+912271264296", "Direction": "inbound"},
    )
    assert res.status_code == 200
    assert 'redirect="true"' in res.text
    assert "vm.mp3" not in res.text  # voicemail is the action handler's call now


def test_dial_action_stays_silent_when_the_call_was_answered(client, tenant_and_user, db, monkeypatch):
    """DialStatus=completed -- someone took the call. Hang up, don't
    apologise for missing it."""
    from app.services import ivr_routing_service

    monkeypatch.setattr(ivr_routing_service, "resolve_voicemail_url", lambda t, **kw: "https://x/vm.mp3")

    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-action",
        data={"CallUUID": "call-vm-2", "DialStatus": "completed"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert "vm.mp3" not in res.text
    assert "<Hangup/>" in res.text


@pytest.mark.parametrize("status", ["no-answer", "busy", "failed", "cancel", "timeout", ""])
def test_dial_action_plays_voicemail_when_nobody_took_the_call(
    client, tenant_and_user, db, monkeypatch, status,
):
    """Every non-completed outcome still reaches voicemail -- including a
    missing DialStatus, which is treated as "not answered" so the caller is
    never left with dead air."""
    from app.services import ivr_routing_service

    monkeypatch.setattr(ivr_routing_service, "resolve_voicemail_url", lambda t, **kw: "https://x/vm.mp3")

    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    payload = {"CallUUID": f"call-vm-{status or 'none'}"}
    if status:
        payload["DialStatus"] = status

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-action",
        data=payload,
    )
    assert res.status_code == 200
    assert "vm.mp3" in res.text
    assert "<Hangup/>" in res.text


def test_dial_action_still_records_agent_attribution(client, tenant_and_user, db):
    """The action handler shares the callbackUrl handler's logic, so moving
    the terminal DialStatus onto its own endpoint must not lose the
    provisional-match promotion that inbound agent attribution depends on."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")
    agent = _add_agent(db, tenant, phone="+919876500055")

    client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-attr-1", "DialBLegTo": "+919876500055"},
    )
    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-action",
        data={"CallUUID": "call-attr-1", "DialStatus": "completed"},
    )
    assert res.status_code == 200

    from app.workers.tasks.call_ingest import _lookup_click_to_call_agent
    assert _lookup_click_to_call_agent(tenant.id, "call-attr-1") == agent.id


def test_answer_webhook_hangs_up_gracefully_when_forward_number_unset(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")  # no forward_number

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/answer",
        data={"CallUUID": "call-abc-123", "From": "+919876543210", "To": "+912271264296"},
    )
    assert res.status_code == 200
    assert "<Hangup" in res.text
    assert "<Record" not in res.text


def test_recording_webhook_merges_cached_answer_data_and_dispatches(client, tenant_and_user, db, monkeypatch):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    # Prime the answer->recording cache bridge exactly as the answer webhook would.
    from app.core.cache import set_cached
    from app.api.v1.endpoints.webhooks_vobiz import _cache_key
    set_cached(
        _cache_key(tenant.id, "call-abc-123"),
        {"From": "+919876543210", "To": "+912271264296", "Direction": "inbound", "started_at": "2026-07-26T10:00:00Z"},
        ttl=60,
    )

    dispatched = {}

    def fake_delay(**kwargs):
        dispatched.update(kwargs)

    from app.workers.tasks import call_ingest
    monkeypatch.setattr(call_ingest.ingest_call, "delay", fake_delay)

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/recording",
        data={
            "CallUUID": "call-abc-123",
            "RecordFile": "https://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-1/",
            "RecordingDuration": "42",
        },
    )
    assert res.status_code == 200
    assert dispatched["tenant_id"] == tenant.id
    assert dispatched["ivr_provider"] == "vobiz"
    assert dispatched["payload"]["CallUUID"] == "call-abc-123"
    assert dispatched["payload"]["From"] == "+919876543210"
    assert dispatched["payload"]["To"] == "+912271264296"
    assert dispatched["payload"]["RecordUrl"] == "https://api.vobiz.ai/api/v1/Account/MA123/Recording/rec-1/"
    assert dispatched["payload"]["RecordingDuration"] == "42"


def test_recording_webhook_ignores_missing_call_uuid(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/recording",
        data={"RecordFile": "https://api.vobiz.ai/x"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# ── Dial-status webhook ──────────────────────────────────────────────────────

def test_dial_status_webhook_ignores_missing_call_uuid(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"DialStatus": "completed"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


def test_dial_status_webhook_does_not_raise_on_unexpected_payload_shape(client, tenant_and_user, db):
    """No DialBLegTo, no DialStatus -- just a CallUUID. Real Vobiz payload
    shape is unconfirmed (see webhooks_vobiz.py's own comment) -- this must
    degrade to a no-op, never a 500."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "SomeUnexpectedField": "x"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def _add_agent(db, tenant, phone="+919000000000", name="Agent Answered"):
    from app.models.user import User, UserRole
    agent = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name=name,
        email=f"agent-{uuid.uuid4().hex[:6]}@test.com", hashed_password="x",
        role=UserRole.RESERVATIONS, phone=phone, is_active=True,
    )
    db.add(agent)
    db.commit()
    return agent


def test_dial_b_leg_to_alone_does_not_yet_attribute_the_call(client, tenant_and_user, db):
    """Real bug, confirmed live: a guest who hung up before anyone answered
    still showed up with an agent's name attached on the Calls page.
    DialBLegTo can appear on a leg that was merely dialed, not one that
    answered -- it must only be a PROVISIONAL match until a terminal
    DialStatus == "completed" confirms an actual connect."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")
    agent = _add_agent(db, tenant)

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialBLegTo": "+919000000000"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    from app.workers.tasks.call_ingest import _lookup_click_to_call_agent
    assert _lookup_click_to_call_agent(tenant.id, "call-abc-123") is None


def test_dial_status_completed_promotes_the_provisional_match(client, tenant_and_user, db):
    """DialBLegTo (one POST) followed by a terminal DialStatus == "completed"
    (a later POST, matching Vobiz's documented separate-events shape) is
    what actually confirms a real connect -- only then is the attribution
    written to the cache call_ingest.py reads."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")
    agent = _add_agent(db, tenant)

    client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialBLegTo": "+919000000000"},
    )
    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialStatus": "completed"},
    )
    assert res.status_code == 200

    from app.workers.tasks.call_ingest import _lookup_click_to_call_agent
    assert _lookup_click_to_call_agent(tenant.id, "call-abc-123") == agent.id


def test_dial_status_no_answer_never_promotes_the_match(client, tenant_and_user, db):
    """The exact scenario the live bug report described: the guest hangs up
    before anyone picks up. DialBLegTo may still show up (a leg was dialed),
    but DialStatus will not be "completed" -- the call must stay
    unattributed."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")
    _add_agent(db, tenant)

    client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialBLegTo": "+919000000000"},
    )
    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialStatus": "no-answer"},
    )
    assert res.status_code == 200

    from app.workers.tasks.call_ingest import _lookup_click_to_call_agent
    assert _lookup_click_to_call_agent(tenant.id, "call-abc-123") is None


def test_dial_status_webhook_no_agent_match_leaves_cache_empty(client, tenant_and_user, db):
    """DialBLegTo that matches no known agent phone -- must not raise, and
    must not cache a bogus attribution."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret")

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialBLegTo": "+919999999999"},
    )
    assert res.status_code == 200

    from app.workers.tasks.call_ingest import _lookup_click_to_call_agent
    assert _lookup_click_to_call_agent(tenant.id, "call-abc-123") is None


def test_dial_status_webhook_caches_dial_status_for_recording_merge(client, tenant_and_user, db, monkeypatch):
    """End-to-end: DialStatus cached by the dial-status webhook must show up
    in the payload the recording webhook hands to ingest_call."""
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="correct-secret", forward_number="+919000000000")

    from app.core.cache import set_cached
    from app.api.v1.endpoints.webhooks_vobiz import _cache_key
    set_cached(
        _cache_key(tenant.id, "call-abc-123"),
        {"From": "+919876543210", "To": "+912271264296", "Direction": "inbound", "started_at": "2026-07-26T10:00:00Z"},
        ttl=60,
    )

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/dial-status",
        data={"CallUUID": "call-abc-123", "DialStatus": "no-answer"},
    )
    assert res.status_code == 200

    dispatched = {}

    def fake_delay(**kwargs):
        dispatched.update(kwargs)

    from app.workers.tasks import call_ingest
    monkeypatch.setattr(call_ingest.ingest_call, "delay", fake_delay)

    res = client.post(
        f"/api/v1/webhooks/vobiz/{tenant.slug}/correct-secret/recording",
        data={"CallUUID": "call-abc-123", "RecordFile": "https://api.vobiz.ai/x", "RecordingDuration": "0"},
    )
    assert res.status_code == 200
    assert dispatched["payload"]["ivr_dial_status"] == "no-answer"


# ── GET /integrations/vobiz/webhook-info ────────────────────────────────────

def test_webhook_info_includes_secret_and_answer_suffix(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id, webhook_secret="my-secret-123")

    res = client.get(
        "/api/v1/integrations/vobiz/webhook-info",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["webhook_url"] == f"https://testserver/api/v1/webhooks/vobiz/{tenant.slug}/my-secret-123/answer"


def test_webhook_info_null_url_before_connect(client, tenant_and_user):
    res = client.get(
        "/api/v1/integrations/vobiz/webhook-info",
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    assert res.json()["webhook_url"] is None
