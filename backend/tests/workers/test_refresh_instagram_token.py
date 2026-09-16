"""Instagram long-lived tokens must never reach expiry.

Ratha's died on 10-Sep-2026 and 36 consecutive bot replies were rejected
by Meta over five days while the concierge kept drafting them. Nothing
refreshed the token and its expiry was never stored, so there was nothing
to alert on until sends were already failing -- at which point Meta treats
the token as permanently non-refreshable and a human must redo OAuth.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.workers.tasks import refresh_instagram_token as rt


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="IG", slug=f"ig-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _integration(db, tenant, token="old-token", refreshed_days_ago=10):
    row = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant.id, kind="instagram", status="active",
        credentials_kms_blob=encrypt_credentials({
            "access_token": token,
            "app_secret": "sek",
            "instagram_business_account_id": "17841400000000000",
        }),
        config={
            "instagram_business_account_id": "17841400000000000",
            "token_refreshed_at": (
                datetime.now(timezone.utc) - timedelta(days=refreshed_days_ago)
            ).isoformat(),
        },
    )
    db.add(row)
    db.commit()
    return row


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture()
def use_db(db, monkeypatch):
    monkeypatch.setattr(rt, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    return db


def test_refresh_stores_new_token_and_expiry(use_db, monkeypatch):
    db = use_db
    t = _tenant(db)
    row = _integration(db, t)

    sent = {}

    def fake_get(url, params=None, timeout=None):
        sent["url"] = url
        sent["params"] = params
        return _Resp(200, {"access_token": "brand-new-token", "expires_in": 5183944})

    monkeypatch.setattr(rt.httpx, "get", fake_get)

    out = rt.refresh_tenant_token(t.id)
    assert out["status"] == "refreshed"
    assert sent["url"] == "https://graph.instagram.com/refresh_access_token"
    assert sent["params"]["grant_type"] == "ig_refresh_token"
    assert sent["params"]["access_token"] == "old-token"

    db.refresh(row)
    assert decrypt_credentials(row.credentials_kms_blob)["access_token"] == "brand-new-token"
    # the whole point: expiry is now knowable instead of implicit
    assert row.config["token_expires_at"]
    expires = datetime.fromisoformat(row.config["token_expires_at"])
    assert expires > datetime.now(timezone.utc) + timedelta(days=55)


def test_refresh_preserves_other_credentials(use_db, monkeypatch):
    """app_secret is needed for the next OAuth; losing it on refresh would
    quietly break reconnection."""
    db = use_db
    t = _tenant(db)
    row = _integration(db, t)
    monkeypatch.setattr(
        rt.httpx, "get",
        lambda *a, **k: _Resp(200, {"access_token": "new", "expires_in": 5183944}),
    )

    rt.refresh_tenant_token(t.id)

    db.refresh(row)
    creds = decrypt_credentials(row.credentials_kms_blob)
    assert creds["app_secret"] == "sek"
    assert creds["instagram_business_account_id"] == "17841400000000000"


def test_token_younger_than_24h_is_skipped(use_db, monkeypatch):
    """Meta rejects a refresh on a token under 24h old -- don't burn the call
    or log a false failure right after someone connects."""
    db = use_db
    t = _tenant(db)
    _integration(db, t, refreshed_days_ago=0)

    def explode(*a, **k):
        raise AssertionError("should not call Meta for a token under 24h old")

    monkeypatch.setattr(rt.httpx, "get", explode)
    assert rt.refresh_tenant_token(t.id)["status"] == "too_young"


def test_expired_token_reports_failure_without_wiping_credentials(use_db, monkeypatch):
    """An already-dead token is non-refreshable and needs fresh OAuth. The
    stored credentials must survive so the reconnect flow still has the
    app_secret."""
    db = use_db
    t = _tenant(db)
    row = _integration(db, t)
    monkeypatch.setattr(
        rt.httpx, "get",
        lambda *a, **k: _Resp(400, {}, text="Error validating access token: Session has expired"),
    )

    out = rt.refresh_tenant_token(t.id)
    assert out["status"] == "refresh_failed"
    assert out["http"] == 400

    db.refresh(row)
    assert decrypt_credentials(row.credentials_kms_blob)["access_token"] == "old-token"
    assert decrypt_credentials(row.credentials_kms_blob)["app_secret"] == "sek"


def test_network_error_is_not_treated_as_a_dead_token(use_db, monkeypatch):
    db = use_db
    t = _tenant(db)
    _integration(db, t)

    def boom(*a, **k):
        raise ConnectionError("dns died")

    monkeypatch.setattr(rt.httpx, "get", boom)
    assert rt.refresh_tenant_token(t.id)["status"] == "network_error"


def test_tenant_without_instagram_is_a_noop(use_db, monkeypatch):
    db = use_db
    t = _tenant(db)
    db.commit()

    def explode(*a, **k):
        raise AssertionError("should not call Meta when Instagram isn't configured")

    monkeypatch.setattr(rt.httpx, "get", explode)
    assert rt.refresh_tenant_token(t.id)["status"] == "not_configured"
