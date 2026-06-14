"""Tests 1-2: DograhAdapter — signature verification and payload parsing."""
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.adapters.voice.dograh import DograhAdapter

adapter = DograhAdapter()

SECRET = "test-secret-abc123"


def _make_sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── Test 1: verify_webhook_signature ─────────────────────────────────────────

def test_verify_signature_valid():
    body = b'{"event":"call.completed"}'
    sig = _make_sig(body, SECRET)
    assert adapter.verify_webhook_signature(body, {"x-dograh-signature": sig}, SECRET) is True


def test_verify_signature_invalid():
    body = b'{"event":"call.completed"}'
    assert adapter.verify_webhook_signature(
        body, {"x-dograh-signature": "bad-signature"}, SECRET
    ) is False


def test_verify_signature_empty_secret_always_rejected():
    body = b'{"event":"call.completed"}'
    sig = _make_sig(body, SECRET)
    assert adapter.verify_webhook_signature(body, {"x-dograh-signature": sig}, "") is False


def test_verify_signature_missing_header():
    body = b'{"event":"call.completed"}'
    assert adapter.verify_webhook_signature(body, {}, SECRET) is False


def test_verify_signature_uses_compare_digest():
    """Confirm implementation uses hmac.compare_digest — check source code."""
    import inspect
    src = inspect.getsource(adapter.verify_webhook_signature)
    assert "compare_digest" in src, "Must use hmac.compare_digest to prevent timing attacks"


# ── Test 2: parse_call_completed_webhook ─────────────────────────────────────

_VALID_PAYLOAD = {
    "event": "call.completed",
    "call_id": "call-abc-123",
    "agent_id": "agent-xyz",
    "phone_number": "+919876543210",
    "direction": "inbound",
    "duration_seconds": 180,
    "status": "completed",
    "transcript": [
        {"speaker": "agent", "text": "Namaste!", "timestamp": 0.0, "language": "hi-IN"},
        {"speaker": "caller", "text": "Hello", "timestamp": 1.5},
    ],
    "recording_url": "https://cdn.dograh.com/rec/abc.mp3",
    "extracted_variables": {
        "intent": "booking",
        "check_in_date": "2026-07-01",
        "check_out_date": "2026-07-03",
        "guest_count": 2,
        "property_name": "Ratha Caravan",
        "sentiment": "positive",
        "language_detected": "hi-IN",
    },
    "ended_at": "2026-06-08T10:00:00Z",
    "tenant_slug": "ratha",
}


def test_parse_valid_payload():
    result = adapter.parse_call_completed_webhook(_VALID_PAYLOAD)
    assert result.call_id == "call-abc-123"
    assert result.direction == "inbound"
    assert result.status == "completed"
    assert result.extracted_variables.intent == "booking"
    assert len(result.transcript) == 2


def test_parse_missing_optional_fields():
    minimal = {**_VALID_PAYLOAD}
    minimal.pop("recording_url")
    minimal["extracted_variables"] = {}
    result = adapter.parse_call_completed_webhook(minimal)
    assert result.recording_url is None
    assert result.extracted_variables.intent is None


def test_parse_invalid_direction_raises():
    bad = {**_VALID_PAYLOAD, "direction": "sideways"}
    with pytest.raises(ValidationError):
        adapter.parse_call_completed_webhook(bad)


def test_parse_invalid_status_raises():
    bad = {**_VALID_PAYLOAD, "status": "unknown_status"}
    with pytest.raises(ValidationError):
        adapter.parse_call_completed_webhook(bad)
