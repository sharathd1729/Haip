"""
WhatsApp module Phase 1, T1.1 — per-tenant webhook secret tests.

Tests:
  Happy path — tenant's own secret verifies and message is queued
  Cross-tenant — a webhook body resolving to tenant B, signed with tenant
    A's secret, is rejected (401)
  Missing secret — tenant with no app_secret configured is rejected (401),
    no shared/global fallback
"""
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403


def _make_sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _NoCloseSessionWrapper:
    """webhooks_whatsapp.py opens its own SessionLocal() for the pre-queue
    tenant/secret lookup -- patch it to the test fixture's session so it
    sees uncommitted fixture data, same pattern as the Instagram webhook
    tests use for the same reason."""
    def __init__(self, real_session):
        self._s = real_session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def _setup_tenant_with_wa_integration(db, app_secret: str, phone_number_id: str):
    import os
    os.environ.setdefault("ENCRYPTION_KEY", "test-fernet-key-must-be-32-urlsafe=")
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

    from app.models.tenant import Tenant
    from app.models.integration import Integration
    from app.core.encryption import encrypt_credentials

    tenant = Tenant(id=str(uuid.uuid4()), name="Test Villa", slug=f"villa-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()

    integration = Integration(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        kind="whatsapp_meta",
        status="active",
        credentials_kms_blob=encrypt_credentials({
            "access_token": "tok", "app_secret": app_secret,
            "phone_number_id": phone_number_id, "waba_id": "waba1",
        }),
        config={"phone_number_id": phone_number_id, "waba_id": "waba1"},
    )
    db.add(integration)
    db.commit()
    return tenant


def _payload(phone_number_id: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": phone_number_id},
                    "messages": [],
                    "statuses": [],
                }
            }]
        }]
    }


def test_happy_path_verifies_with_own_secret(client, db):
    tenant = _setup_tenant_with_wa_integration(db, "secretA", "1000")
    body = json.dumps(_payload("1000")).encode()
    sig = _make_sig(body, "secretA")

    with patch("app.api.v1.endpoints.webhooks_whatsapp.SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.whatsapp.process_whatsapp_message.delay"):
        resp = client.post(
            "/api/v1/webhooks/whatsapp", content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200


def test_cross_tenant_secret_rejected(client, db):
    """A webhook resolving to tenant B's phone_number_id, signed with
    tenant A's secret, must be rejected -- not verifiable against B's own
    (different) secret."""
    _setup_tenant_with_wa_integration(db, "secretA", "1000")
    _setup_tenant_with_wa_integration(db, "secretB", "2000")

    body = json.dumps(_payload("2000")).encode()   # targets tenant B
    sig = _make_sig(body, "secretA")                # signed with tenant A's secret

    with patch("app.api.v1.endpoints.webhooks_whatsapp.SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.whatsapp.process_whatsapp_message.delay"):
        resp = client.post(
            "/api/v1/webhooks/whatsapp", content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 401


def test_missing_secret_rejected_no_global_fallback(client, db):
    import os
    os.environ.setdefault("ENCRYPTION_KEY", "test-fernet-key-must-be-32-urlsafe=")
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

    from app.models.tenant import Tenant
    from app.models.integration import Integration
    from app.core.encryption import encrypt_credentials

    tenant = Tenant(id=str(uuid.uuid4()), name="No Secret Villa", slug=f"nosec-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant.id, kind="whatsapp_meta", status="active",
        config={"phone_number_id": "3000", "waba_id": "waba1"},
        # phone_number_id present so the tenant resolves, but app_secret
        # deliberately omitted -- this tenant never configured one.
        credentials_kms_blob=encrypt_credentials({
            "access_token": "tok", "phone_number_id": "3000", "waba_id": "waba1",
        }),
    )
    db.add(integration)
    db.commit()

    body = json.dumps(_payload("3000")).encode()
    sig = _make_sig(body, "irrelevant")

    with patch("app.api.v1.endpoints.webhooks_whatsapp.SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.whatsapp.process_whatsapp_message.delay"):
        resp = client.post(
            "/api/v1/webhooks/whatsapp", content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 401
