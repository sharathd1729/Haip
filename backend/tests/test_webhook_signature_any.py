"""verify_meta_signature_any -- a wrong tenant secret must not kill inbound.

Confirmed live on Ratha (16-Sep-2026): an Instagram reconnect overwrote a
working app_secret. Meta kept delivering every DM; every one logged
webhook_signature_mismatch and was dropped, because the handler only fell
back to META_APP_SECRET when the tenant value was *empty*, not *wrong*.
"""
import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.core.webhook_security import verify_meta_signature_any

BODY = b'{"object":"instagram","entry":[{"id":"17841438895410028"}]}'


def sign(secret: str, body: bytes = BODY) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_wrong_tenant_secret_still_verifies_via_server_secret():
    """The exact outage: tenant secret wrong, server secret right."""
    matched = verify_meta_signature_any(
        BODY, sign("real-app-secret"), "production",
        [("tenant_app_secret", "mistyped-secret"), ("META_APP_SECRET", "real-app-secret")],
    )
    assert matched == "META_APP_SECRET"


def test_correct_tenant_secret_is_preferred():
    matched = verify_meta_signature_any(
        BODY, sign("tenant-secret"), "production",
        [("tenant_app_secret", "tenant-secret"), ("META_APP_SECRET", "server-secret")],
    )
    assert matched == "tenant_app_secret"


def test_forged_signature_matching_no_held_secret_is_rejected():
    """Accepting any of OUR secrets must not mean accepting anything."""
    with pytest.raises(HTTPException) as exc:
        verify_meta_signature_any(
            BODY, sign("attacker-secret"), "production",
            [("tenant_app_secret", "tenant-secret"), ("META_APP_SECRET", "server-secret")],
        )
    assert exc.value.status_code == 401


def test_tampered_body_is_rejected():
    sig = sign("server-secret")
    with pytest.raises(HTTPException):
        verify_meta_signature_any(
            BODY + b"tampered", sig, "production", [("META_APP_SECRET", "server-secret")],
        )


def test_missing_signature_header_is_rejected():
    with pytest.raises(HTTPException) as exc:
        verify_meta_signature_any(BODY, "", "production", [("META_APP_SECRET", "server-secret")])
    assert exc.value.status_code == 401


def test_blank_secrets_are_ignored_not_matched():
    """A blank candidate must never become an empty-key HMAC that matches."""
    with pytest.raises(HTTPException):
        verify_meta_signature_any(
            BODY, sign(""), "production",
            [("tenant_app_secret", ""), ("META_APP_SECRET", "server-secret")],
        )


def test_no_secrets_fails_closed_in_production():
    with pytest.raises(HTTPException) as exc:
        verify_meta_signature_any(BODY, sign("x"), "production", [("tenant_app_secret", "")])
    assert exc.value.status_code == 401


def test_no_secrets_allowed_in_development():
    assert verify_meta_signature_any(BODY, "", "development", []) == "none"
