"""
T1.1 / T2.5 — Tests for the Instagram comment webhook path.

Tests:
  Happy path — valid signature, comment webhook queues process_instagram_comment
  Invalid signature → 401
  Self-reply (business account's own comment) is skipped, not queued
  Non-comments change fields are ignored without erroring
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403 — bring in db, client, tenant_and_user fixtures


def _make_sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _NoCloseSessionWrapper:
    """
    webhooks_instagram.py's secret-lookup opens its own `SessionLocal()`
    instead of using the injected `db` dependency (unlike webhooks_dograh.py,
    which correctly uses Depends(get_db)) -- a separate connection can't see
    the test fixture's uncommitted transaction. Patching SessionLocal to
    return the shared test session works around this without changing
    production code; the no-op close() stops the webhook's `finally: db.close()`
    from tearing down the fixture's session mid-test.
    """
    def __init__(self, real_session):
        self._s = real_session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def _setup_tenant_with_ig_integration(db, app_secret: str, ig_account_id: str):
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
        kind="instagram",
        status="active",
        credentials_kms_blob=encrypt_credentials({"app_secret": app_secret, "access_token": "test-token"}),
        config={"instagram_business_account_id": ig_account_id},
    )
    db.add(integration)
    db.commit()
    return tenant


def _comment_payload(ig_account_id: str, sender_id: str, comment_id: str, text: str = "what's the price?") -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": ig_account_id,
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": comment_id,
                            "text": text,
                            "from": {"id": sender_id, "username": "test_guest"},
                            "media": {"id": "media-123"},
                        },
                    }
                ],
            }
        ],
    }


# ── Happy path ────────────────────────────────────────────────────────────────

def test_comment_webhook_happy_path_queues_task(client, db):
    ig_account_id = "ig-biz-001"
    tenant = _setup_tenant_with_ig_integration(db, "comment-secret", ig_account_id)
    payload = _comment_payload(ig_account_id, sender_id="guest-001", comment_id="comment-001")
    body = json.dumps(payload).encode()
    sig = _make_sig(body, "comment-secret")

    with patch("app.core.database.SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_comment.process_instagram_comment") as mock_task:
        mock_task.delay = lambda *a, **kw: None
        resp = client.post(
            "/api/v1/webhooks/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Invalid signature → 401 ──────────────────────────────────────────────────

def test_comment_webhook_invalid_signature(client, db):
    ig_account_id = "ig-biz-002"
    _setup_tenant_with_ig_integration(db, "correct-secret", ig_account_id)
    payload = _comment_payload(ig_account_id, sender_id="guest-002", comment_id="comment-002")
    body = json.dumps(payload).encode()

    with patch("app.core.database.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = client.post(
            "/api/v1/webhooks/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=wrong"},
        )

    assert resp.status_code == 401


# ── Self-reply skipped, not queued ───────────────────────────────────────────

def test_comment_webhook_self_reply_skipped(client, db):
    ig_account_id = "ig-biz-003"
    _setup_tenant_with_ig_integration(db, "self-reply-secret", ig_account_id)
    # sender_id == ig_account_id -- the business account replying to its own thread
    payload = _comment_payload(ig_account_id, sender_id=ig_account_id, comment_id="comment-003")
    body = json.dumps(payload).encode()
    sig = _make_sig(body, "self-reply-secret")

    with patch("app.core.database.SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_comment.process_instagram_comment") as mock_task:
        mock_task.delay = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be queued"))
        resp = client.post(
            "/api/v1/webhooks/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )

    assert resp.status_code == 200


# ── Unrelated change field ignored without erroring ──────────────────────────

def test_webhook_ignores_non_comment_change_fields(client, db):
    ig_account_id = "ig-biz-004"
    _setup_tenant_with_ig_integration(db, "other-field-secret", ig_account_id)
    payload = {
        "object": "instagram",
        "entry": [
            {"id": ig_account_id, "changes": [{"field": "mentions", "value": {"comment_id": "x"}}]},
        ],
    }
    body = json.dumps(payload).encode()
    sig = _make_sig(body, "other-field-secret")

    with patch("app.core.database.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = client.post(
            "/api/v1/webhooks/instagram",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )

    assert resp.status_code == 200
