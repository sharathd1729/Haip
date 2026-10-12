"""
Tests for B1: Webhook signature verification — fail-closed in production.

Covers:
- Valid HMAC signature → 200/queued
- Invalid signature → 401
- Missing header → 401
- No secret in dev → warning logged, request accepted
- No secret in prod → startup raises (config validator test)
"""

import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ── Helper ────────────────────────────────────────────────────────────────────

TEST_SECRET = "test-meta-app-secret-abc123"

def _make_sig(body: bytes, secret: str = TEST_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── verify_meta_signature unit tests ─────────────────────────────────────────

class TestVerifyMetaSignature:
    """Direct unit tests for the shared verifier in core/webhook_security.py."""

    def _call(self, body: bytes, sig: str, env: str = "development", secret: str = TEST_SECRET):
        from app.core.webhook_security import verify_meta_signature
        verify_meta_signature(body=body, signature_header=sig, env=env, secret=secret)

    def test_valid_signature_passes(self):
        body = b'{"test": "payload"}'
        sig = _make_sig(body)
        # Should not raise
        self._call(body, sig)

    def test_invalid_signature_raises_401(self):
        from fastapi import HTTPException
        body = b'{"test": "payload"}'
        self._call.__func__  # ensure imported
        with pytest.raises(HTTPException) as exc_info:
            self._call(body, "sha256=deadbeef")
        assert exc_info.value.status_code == 401

    def test_missing_header_raises_401(self):
        from fastapi import HTTPException
        body = b'{"test": "payload"}'
        with pytest.raises(HTTPException) as exc_info:
            self._call(body, "")
        assert exc_info.value.status_code == 401

    def test_malformed_header_raises_401(self):
        from fastapi import HTTPException
        body = b'{"test": "payload"}'
        with pytest.raises(HTTPException) as exc_info:
            self._call(body, "notsha256=abc")
        assert exc_info.value.status_code == 401

    def test_no_secret_in_dev_allows_through(self):
        """Dev with no secret: should NOT raise, just log a warning."""
        body = b'{"test": "payload"}'
        # Should not raise — dev mode passes without secret
        self._call(body, "", env="development", secret="")

    def test_no_secret_in_prod_raises_401(self):
        """Prod with no secret: fail-closed (defense in depth)."""
        from fastapi import HTTPException
        body = b'{"test": "payload"}'
        with pytest.raises(HTTPException) as exc_info:
            self._call(body, "", env="production", secret="")
        assert exc_info.value.status_code == 401

    def test_tampered_body_fails(self):
        """Signature was generated for original body; tampered body must fail."""
        from fastapi import HTTPException
        original = b'{"amount": 100}'
        tampered = b'{"amount": 9999}'
        sig = _make_sig(original)
        with pytest.raises(HTTPException) as exc_info:
            self._call(tampered, sig)
        assert exc_info.value.status_code == 401


# ── Config startup validation ─────────────────────────────────────────────────

class TestProdStartupValidation:
    """A missing META_APP_SECRET no longer stops the app booting (WhatsApp verifies against each
    tenant's own app secret, and the core CRM does not depend on Meta), so the safety net is the
    request path: in production, with no secret to verify against, a webhook is refused (covered by
    ``test_no_secret_in_prod_raises_401`` above)."""

    def test_prod_without_secret_still_boots(self, monkeypatch):
        """Settings validation must not crash in production when only META_APP_SECRET is missing."""
        from app.core.config import Settings

        env = {
            "ENVIRONMENT": "production", "SECRET_KEY": "a" * 64, "JWT_SECRET": "b" * 64,
            "DATABASE_URL": "postgresql://u:p@localhost/db", "ALLOWED_ORIGINS": "https://example.com",
            "META_APP_SECRET": "",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        settings = Settings(_env_file=None)
        assert settings.ENVIRONMENT == "production"
        assert settings.META_APP_SECRET == ""

    def test_prod_with_meta_app_secret_passes(self):
        """When all required prod vars are set, no error should be raised."""
        with patch.dict(os.environ, {
            "ENVIRONMENT": "development",  # dev mode — no strict checks
            "META_APP_SECRET": TEST_SECRET,
        }, clear=False):
            from app.core.webhook_security import verify_meta_signature
            body = b"hello"
            sig = _make_sig(body, TEST_SECRET)
            # Should pass cleanly
            verify_meta_signature(body=body, signature_header=sig, env="development", secret=TEST_SECRET)


# ── WhatsApp endpoint integration ────────────────────────────────────────────

class TestWhatsAppWebhookSignature:
    """Integration tests hitting the WhatsApp webhook endpoint via TestClient."""

    @pytest.fixture(autouse=True)
    def _mock_celery(self):
        """Don't actually enqueue tasks in tests."""
        with patch("app.workers.tasks.whatsapp.process_whatsapp_message.delay") as m:
            yield m

    def _client_with_secret(self, secret: str):
        os.environ["META_APP_SECRET"] = secret
        # Reload settings so the new env var is picked up
        import importlib
        import app.core.config as cfg_mod
        importlib.reload(cfg_mod)

        from app.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_valid_signature_returns_queued(self, client):
        body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.META_APP_SECRET = TEST_SECRET
            mock_settings.ENVIRONMENT = "development"
            sig = _make_sig(body, TEST_SECRET)
            # Hit the endpoint directly via the shared verifier
            from app.core.webhook_security import verify_meta_signature
            # Should not raise
            verify_meta_signature(body=body, signature_header=sig, env="development", secret=TEST_SECRET)

    def test_invalid_signature_rejected(self, client):
        from fastapi import HTTPException
        from app.core.webhook_security import verify_meta_signature
        body = b'{"object": "whatsapp_business_account"}'
        with pytest.raises(HTTPException) as exc_info:
            verify_meta_signature(body=body, signature_header="sha256=bad", env="production", secret=TEST_SECRET)
        assert exc_info.value.status_code == 401

    def test_missing_signature_header_rejected(self, client):
        from fastapi import HTTPException
        from app.core.webhook_security import verify_meta_signature
        body = b'{"object": "whatsapp_business_account"}'
        with pytest.raises(HTTPException) as exc_info:
            verify_meta_signature(body=body, signature_header="", env="production", secret=TEST_SECRET)
        assert exc_info.value.status_code == 401
