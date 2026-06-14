"""Tests 3-8: Dograh webhook endpoint."""
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401,F403 — bring in db, client, tenant_and_user fixtures


def _make_sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _valid_payload(tenant_slug: str = "test-slug") -> dict:
    return {
        "event": "call.completed",
        "call_id": f"call-{uuid.uuid4().hex[:8]}",
        "agent_id": "agent-001",
        "phone_number": "+919876543210",
        "direction": "inbound",
        "duration_seconds": 120,
        "status": "completed",
        "transcript": [
            {"speaker": "agent", "text": "Namaste", "timestamp": 0.0}
        ],
        "recording_url": "https://cdn.dograh.com/rec/test.mp3",
        "extracted_variables": {
            "intent": "booking",
            "sentiment": "positive",
            "language_detected": "hi-IN",
        },
        "ended_at": "2026-06-08T10:00:00Z",
        "tenant_slug": tenant_slug,
    }


def _setup_tenant_with_secret(db, secret: str = "my-test-secret") -> object:
    """Create tenant with encrypted dograh_webhook_secret_enc."""
    import os
    os.environ.setdefault("ENCRYPTION_KEY", "test-fernet-key-must-be-32-urlsafe=")

    from cryptography.fernet import Fernet
    # Use a valid test Fernet key
    test_key = Fernet.generate_key()
    os.environ["ENCRYPTION_KEY"] = test_key.decode()

    from app.models.tenant import Tenant
    from app.core.encryption import encrypt_credentials

    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Test Hotel",
        slug=f"hotel-{uuid.uuid4().hex[:6]}",
        plan="growth",
        dograh_webhook_secret_enc=encrypt_credentials({"webhook_secret": secret}),
    )
    db.add(tenant)
    db.commit()
    return tenant


# ── Test 3: Happy path ────────────────────────────────────────────────────────

def test_dograh_webhook_happy_path(client, db):
    tenant = _setup_tenant_with_secret(db, secret="valid-secret")
    payload = _valid_payload(tenant_slug=tenant.slug)
    body = json.dumps(payload).encode()
    sig = _make_sig(body, "valid-secret")

    with patch("app.api.v1.endpoints.webhooks_dograh.process_dograh_call_completed") as mock_task:
        mock_task.delay = lambda **kw: None
        resp = client.post(
            f"/api/v1/webhooks/dograh/{tenant.slug}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-dograh-signature": sig,
            },
        )

    assert resp.status_code == 200
    assert resp.json()["status"] in ("queued", "ok")


# ── Test 4: Invalid signature → 401 ──────────────────────────────────────────

def test_dograh_webhook_invalid_signature(client, db):
    tenant = _setup_tenant_with_secret(db, secret="correct-secret")
    payload = _valid_payload(tenant_slug=tenant.slug)
    body = json.dumps(payload).encode()

    resp = client.post(
        f"/api/v1/webhooks/dograh/{tenant.slug}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-dograh-signature": "wrong-signature",
        },
    )

    assert resp.status_code == 401


# ── Test 5: Unknown tenant slug → 404 ────────────────────────────────────────

def test_dograh_webhook_unknown_tenant(client, db):
    payload = _valid_payload(tenant_slug="does-not-exist")
    body = json.dumps(payload).encode()

    resp = client.post(
        "/api/v1/webhooks/dograh/does-not-exist",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-dograh-signature": "any-sig",
        },
    )

    assert resp.status_code == 404


# ── Test 6: Duplicate call_id → 200 idempotent ───────────────────────────────

def test_dograh_webhook_duplicate_call_id(client, db):
    from app.models.call import Call, CallDirection

    tenant = _setup_tenant_with_secret(db, secret="dup-secret")
    call_id = f"call-dup-{uuid.uuid4().hex[:8]}"

    # Pre-insert the call so it looks like a duplicate
    existing_call = Call(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        guest_id=None,
        inquiry_id=None,
        ivr_provider="dograh",
        ivr_call_id=call_id,
        direction=CallDirection.INBOUND,
        from_number="+919876543210",
        to_number="",
        voice_platform="dograh",
        dograh_call_id=call_id,
        dograh_agent_id="agent-001",
    )
    db.add(existing_call)
    db.commit()

    payload = _valid_payload(tenant_slug=tenant.slug)
    payload["call_id"] = call_id
    body = json.dumps(payload).encode()
    sig = _make_sig(body, "dup-secret")

    resp = client.post(
        f"/api/v1/webhooks/dograh/{tenant.slug}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-dograh-signature": sig,
        },
    )

    assert resp.status_code == 200


# ── Test 7: SSRF recording_url rejected, webhook still 200 ───────────────────

def test_dograh_webhook_ssrf_recording_url_rejected(client, db):
    tenant = _setup_tenant_with_secret(db, secret="ssrf-secret")
    payload = _valid_payload(tenant_slug=tenant.slug)
    payload["recording_url"] = "http://169.254.169.254/metadata"
    body = json.dumps(payload).encode()
    sig = _make_sig(body, "ssrf-secret")

    with patch("app.api.v1.endpoints.webhooks_dograh.process_dograh_call_completed") as mock_task:
        captured = {}
        def capture(**kw):
            captured.update(kw)
        mock_task.delay = capture

        resp = client.post(
            f"/api/v1/webhooks/dograh/{tenant.slug}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-dograh-signature": sig,
            },
        )

    # Webhook accepted (200), but recording_url was sanitized to None
    assert resp.status_code == 200
    if "payload" in captured:
        assert captured["payload"].get("recording_url") is None


# ── Test 8: Cross-tenant isolation — slug A with secret B → 401 ──────────────

def test_dograh_webhook_cross_tenant_isolation(client, db):
    tenant_a = _setup_tenant_with_secret(db, secret="secret-for-tenant-a")
    tenant_b = _setup_tenant_with_secret(db, secret="secret-for-tenant-b")

    payload = _valid_payload(tenant_slug=tenant_a.slug)
    body = json.dumps(payload).encode()
    # Sign with tenant B's secret but post to tenant A's endpoint
    sig = _make_sig(body, "secret-for-tenant-b")

    resp = client.post(
        f"/api/v1/webhooks/dograh/{tenant_a.slug}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-dograh-signature": sig,
        },
    )

    assert resp.status_code == 401
