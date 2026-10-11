"""Warn before a Meta access token ends: stored end date, once-per-threshold emails, amber/red health."""
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.core.cache import get_cached
from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.services import integration_health as ih
from app.services import meta_token_expiry as mte
from app.workers.tasks.check_meta_credentials import check_tenant_credentials

import pytest
from cryptography.fernet import Fernet

DAY = 86400


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    """Integration credentials are stored encrypted; give each test its own key."""
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


def _now_plus(days: float) -> int:
    return int(time.time() + days * DAY)


def test_bucket_thresholds():
    assert mte.bucket(40) is None
    assert mte.bucket(30) == 30 and mte.bucket(20) == 30
    assert mte.bucket(14) == 14 and mte.bucket(10) == 14
    assert mte.bucket(7) == 7 and mte.bucket(5) == 7
    assert mte.bucket(3) == 3 and mte.bucket(2) == 3
    assert mte.bucket(1) == 1
    assert mte.bucket(0) == 0 and mte.bucket(-4) == 0


def test_fetch_expiry_reads_meta_and_treats_zero_as_never(monkeypatch):
    def fake_get(url, **kw):
        r = MagicMock()
        r.json.return_value = {"data": {"is_valid": True, "expires_at": 0}}
        return r
    monkeypatch.setattr(mte.httpx, "get", fake_get)
    assert mte.fetch_expiry("t") == {"valid": True, "expires_at": 0}

    monkeypatch.setattr(mte.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network")))
    assert mte.fetch_expiry("t") is None          # a network failure is not evidence about the token

    monkeypatch.setattr(mte.httpx, "get", lambda *a, **k: MagicMock(json=lambda: {"error": {"message": "Cannot parse access token"}}))
    assert mte.fetch_expiry("t") is None          # an Instagram Login token is not a Graph token


def test_health_goes_amber_inside_two_weeks_and_red_once_ended():
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    far = {"token_expires_at": (now + timedelta(days=44)).isoformat()}
    soon = {"token_expires_at": (now + timedelta(days=10)).isoformat()}
    gone = {"token_expires_at": (now - timedelta(days=1)).isoformat()}
    assert ih.classify("whatsapp_meta", "active", None, now, config=far) == ih.GREEN
    assert ih.classify("whatsapp_meta", "active", None, now, config=soon) == ih.YELLOW
    assert ih.classify("whatsapp_meta", "active", None, now, config=gone) == ih.RED
    assert ih.classify("whatsapp_meta", "active", None, now, config={}) == ih.GREEN       # never expires / not checked
    assert ih.classify("whatsapp_meta", "disconnected", None, now, config=soon) == ih.OFF


def _wa(db, tenant_id):
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        config={"phone_number_id": "pn1"}, credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
    )
    db.add(integ); db.commit()
    return integ


def _run(db, tenant_id, expiry):
    ok = MagicMock(); ok.status_code = 200; ok.raise_for_status = lambda: None; ok.text = ""
    with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
         patch("httpx.get", return_value=ok), \
         patch("app.services.meta_token_expiry.fetch_expiry", return_value=expiry), \
         patch("app.services.email_service.send_token_expiring_alert_email", return_value=True) as mail:
        result = check_tenant_credentials.run(tenant_id=tenant_id)
    return result, mail


def test_expiring_token_is_stored_and_alerts_once_per_threshold(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    integ_id = _wa(db, tid).id
    expiry = {"valid": True, "expires_at": _now_plus(10)}

    result, mail = _run(db, tid, expiry)
    assert mail.call_count == 1
    kw = mail.call_args.kwargs
    assert kw["to_email"] == tenant_and_user["user"].email and kw["channel"] == "whatsapp" and kw["days_left"] in (9, 10)
    saved = db.get(Integration, integ_id)          # the task closes the shared test session
    assert "token_expires_at" in saved.config and saved.config["phone_number_id"] == "pn1"   # existing config kept

    _, mail2 = _run(db, tid, expiry)                 # same threshold again: no second email
    assert mail2.call_count == 0


def test_far_away_or_never_expiring_token_sends_nothing(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    integ = _wa(db, tid)
    integ_id = integ.id
    _, mail = _run(db, tid, {"valid": True, "expires_at": _now_plus(60)})
    assert mail.call_count == 0

    integ = db.get(Integration, integ_id)
    integ.config = {**integ.config, "token_expires_at": "2026-11-24T00:00:00+00:00"}; db.commit()
    _, mail = _run(db, tid, {"valid": True, "expires_at": 0})          # became a never-expiring token
    assert mail.call_count == 0 and "token_expires_at" not in db.get(Integration, integ_id).config


def test_other_workspace_is_not_touched(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    other = Integration(
        id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), kind="whatsapp_meta", status="active",
        config={}, credentials_kms_blob=encrypt_credentials({"access_token": "other"}),
    )
    _wa(db, tid)
    db.add(other); db.commit()
    other_id = other.id
    _run(db, tid, {"valid": True, "expires_at": _now_plus(5)})
    assert "token_expires_at" not in (db.get(Integration, other_id).config or {})
