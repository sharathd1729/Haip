"""SMS9 parity Track D: the public API usage log (written per call, pruned after 30 days, per workspace) and the Google
Sheets lead sync (address validation, retries, roles, workspace isolation)."""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app as main_app
from app.models.api_usage_log import ApiUsageLog
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.public_api.app import app as public_app
from app.services import api_key_service, api_usage_service
from app.services import google_sheets_service as gs
from fastapi.testclient import TestClient

GOOD_URL = "https://script.google.com/macros/s/AKfycbx" + "a" * 40 + "/exec"


@pytest.fixture()
def http(db):
    def _db():
        yield db
    public_app.dependency_overrides[get_db] = _db
    main_app.dependency_overrides[get_db] = _db
    with TestClient(main_app) as c:
        yield c
    public_app.dependency_overrides.clear()
    main_app.dependency_overrides.clear()


class _Shared:
    """Stands in for SessionLocal(): the test's own session, so writers that open their own session see test rows."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


class _Google:
    """Stands in for the httpx module inside google_sheets_service (patching httpx.Client.post would hit TestClient too)."""
    HTTPError = httpx.HTTPError

    def __init__(self, status):
        self.status, self.sent = status, []

    def Client(self, **_kw):  # noqa: N802 -- mirrors httpx.Client
        outer = self

        class _C:
            def post(self, url, json=None, headers=None):
                outer.sent.append(json)
                return httpx.Response(outer.status)

            def close(self):
                pass
        return _C()


def _google(status):
    return patch("app.services.google_sheets_service.httpx", _Google(status))


def _tid(tu):
    return tu["tenant"].id


def _auth(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="Meera", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": role.value})}


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


# ─── API usage log ──────────────────────────────────────────────────────────

def test_each_public_api_call_is_logged_with_its_route_template(db, tenant_and_user, http, monkeypatch):
    tid = _tid(tenant_and_user)
    key, raw = api_key_service.create_key(db, tid, "Ops", ["properties:read"], None, None)
    db.commit()
    calls = []
    monkeypatch.setattr(api_usage_service, "record", lambda *a: calls.append(a))
    assert http.get("/api/public/v1/properties", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    assert http.get("/api/public/v1/bookings/abc", headers={"Authorization": f"Bearer {raw}"}).status_code == 403
    assert http.get("/api/public/v1/properties", headers={"Authorization": "Bearer haip_live_nope"}).status_code == 401
    assert [(c[0], c[1], c[2], c[3], c[4]) for c in calls] == [
        (tid, key.id, "GET", "/properties", 200), (tid, key.id, "GET", "/bookings/{booking_id}", 403)]
    assert all(isinstance(c[5], int) and c[5] >= 0 for c in calls)


def test_usage_rows_are_written_listed_and_kept_per_workspace(db, tenant_and_user, http, monkeypatch):
    tid = _tid(tenant_and_user)
    key, _ = api_key_service.create_key(db, tid, "Ops", ["properties:read"], None, None)
    other = _other_tenant(db)
    okey, _ = api_key_service.create_key(db, other.id, "Theirs", ["properties:read"], None, None)
    db.commit()
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: _Shared(db))
    api_usage_service.record(tid, key.id, "GET", "/properties", 200, 41)
    api_usage_service.record(other.id, okey.id, "GET", "/properties", 200, 12)
    db.add(ApiUsageLog(tenant_id=tid, api_key_id=key.id, method="GET", path="/bookings", status_code=200, duration_ms=9,
                       created_at=datetime.now(UTC) - timedelta(days=8)))
    db.commit()
    owner = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    body = http.get(f"/api/v1/api-keys/{key.id}/usage", headers=owner).json()
    assert body["calls_7d"] == 1 and len(body["recent"]) == 2
    assert body["recent"][0] == {**body["recent"][0], "method": "GET", "path": "/properties", "status": 200, "duration_ms": 41}
    assert http.get(f"/api/v1/api-keys/{okey.id}/usage", headers=owner).status_code == 404       # another workspace's key
    assert http.get(f"/api/v1/api-keys/{key.id}/usage", headers=_auth(db, tid, UserRole.CONCIERGE)).status_code == 403


def test_a_failed_usage_write_is_swallowed(monkeypatch):
    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("db down")
        add = commit = execute

        def rollback(self):
            pass

        def close(self):
            pass
    monkeypatch.setattr("app.core.database.SessionLocal", Broken)
    monkeypatch.setattr("app.core.database.set_tenant_context", lambda *a: None)
    api_usage_service.record("t", "k", "GET", "/properties", 200, 5)       # must not raise


def test_usage_older_than_30_days_is_pruned_daily(db, tenant_and_user, monkeypatch):
    from app.workers.tasks import webhook_delivery
    tid = _tid(tenant_and_user)
    key, _ = api_key_service.create_key(db, tid, "Ops", ["properties:read"], None, None)
    for days in (31, 2):
        db.add(ApiUsageLog(tenant_id=tid, api_key_id=key.id, method="GET", path="/properties", status_code=200,
                           duration_ms=5, created_at=datetime.now(UTC) - timedelta(days=days)))
    db.commit()
    monkeypatch.setattr(webhook_delivery, "SessionLocal", lambda: _Shared(db))
    webhook_delivery.purge_old()
    left = db.query(ApiUsageLog).filter_by(tenant_id=tid).all()
    assert len(left) == 1 and (datetime.now(UTC) - left[0].created_at.replace(tzinfo=UTC)).days < 30


# ─── Google Sheets lead sync ────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://script.google.com/macros/s/AKfycbxaaaaaaaaaaaaaaaaaaaaaaa/exec",            # not https
    "https://script.google.com.evil.example/macros/s/AKfycbxaaaaaaaaaaaaaaaaaaaaa/exec",
    "https://evil.example/?u=https://script.google.com/macros/s/AKfycbxaaaaaaaaaaaaaaaaa/exec",
    "https://script.google.com/macros/s/AKfycbxaaaaaaaaaaaaaaaaaaaaaa/dev",           # test deployment needs a login
    "https://169.254.169.254/latest/meta-data",
    "",
])
def test_only_apps_script_web_app_addresses_are_accepted(url):
    assert gs.valid_url(url) is False


def test_owner_saves_the_address_encrypted_and_switches_it_on(db, tenant_and_user, http):
    tid = _tid(tenant_and_user)
    owner = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = http.put("/api/v1/google-sheets", json={"url": "https://example.com/hook", "enabled": True}, headers=owner)
    assert r.status_code == 422 and "Apps Script" in r.json()["detail"]
    assert http.put("/api/v1/google-sheets", json={"enabled": True}, headers=owner).status_code == 422   # nothing saved yet
    r = http.put("/api/v1/google-sheets", json={"url": GOOD_URL, "enabled": True}, headers=owner)
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["url_hint"].endswith("/exec")
    row = gs.get_row(db, tid)
    assert GOOD_URL.encode() not in bytes(row.credentials_kms_blob)                     # stored encrypted
    assert http.get("/api/v1/google-sheets", headers=owner).json()["connected"] is True


def test_roles_and_workspaces_for_the_sheet_settings(db, tenant_and_user, http):
    tid = _tid(tenant_and_user)
    manager, concierge = _auth(db, tid, UserRole.MANAGER), _auth(db, tid, UserRole.CONCIERGE)
    assert http.put("/api/v1/google-sheets", json={"url": GOOD_URL, "enabled": True}, headers=manager).status_code == 403
    assert http.get("/api/v1/google-sheets", headers=concierge).status_code == 403
    assert http.post("/api/v1/google-sheets/test", headers=concierge).status_code == 403
    other = _other_tenant(db)
    gs.save(db, other.id, GOOD_URL, True)
    db.commit()
    mine = http.get("/api/v1/google-sheets", headers=manager).json()
    assert mine["connected"] is False and mine["enabled"] is False                       # their sheet is not mine


def test_send_a_test_row_reports_success_and_failure(db, tenant_and_user, http):
    tid = _tid(tenant_and_user)
    gs.save(db, tid, GOOD_URL, True)
    db.commit()
    owner = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    with _google(302) as google:
        body = http.post("/api/v1/google-sheets/test", headers=owner).json()
    assert body["ok"] is True and "test row" in body["message"] and body["rows_sent"] == 0
    assert google.sent[0]["name"] == "Test row from HAIP"
    with _google(404):
        body = http.post("/api/v1/google-sheets/test", headers=owner).json()
    assert body["ok"] is False and "Anyone" in body["message"] and body["last_error"]


def test_a_new_lead_queues_one_sheet_row_with_the_lead_fields(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    gs.save(db, tid, GOOD_URL, True)
    db.commit()
    with patch("app.workers.tasks.webhook_delivery.send_sheet_row.delay") as delay:
        g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Shetty", phone="+919845012345",
                  lead_identified_at=datetime.now(UTC), lead_identified_via="whatsapp")
        db.add(g)
        db.commit()
        g.name = "Kiran S."
        db.commit()
    delay.assert_called_once_with(tenant_id=tid, guest_id=g.id)
    row = gs.lead_row(db, tid, g.id)
    assert row["name"] == "Kiran S." and row["phone"] == "+919845012345" and row["source"] == "whatsapp"
    assert set(row) == {"name", "phone", "source", "created_at", "stage", "first_message"}


def test_no_sheet_row_when_switched_off_or_for_another_workspace(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    gs.save(db, tid, GOOD_URL, False)
    other = _other_tenant(db)
    db.commit()
    with patch("app.workers.tasks.webhook_delivery.send_sheet_row.delay") as delay:
        db.add(Guest(id=str(uuid.uuid4()), tenant_id=tid, name="A", phone="+919800000001", lead_identified_at=datetime.now(UTC)))
        db.add(Guest(id=str(uuid.uuid4()), tenant_id=other.id, name="B", phone="+919800000002", lead_identified_at=datetime.now(UTC)))
        db.commit()
    delay.assert_not_called()


def test_the_sheet_task_retries_a_temporary_failure_but_not_a_wrong_address(db, tenant_and_user, monkeypatch):
    from celery.exceptions import Retry
    from app.workers.tasks import webhook_delivery
    tid = _tid(tenant_and_user)
    gs.save(db, tid, GOOD_URL, True)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran", phone="+919845012345")
    db.add(g)
    db.commit()
    monkeypatch.setattr(webhook_delivery, "SessionLocal", lambda: _Shared(db))
    with _google(500), \
            patch.object(webhook_delivery.send_sheet_row, "retry", side_effect=Retry()) as retry:
        with pytest.raises(Retry):
            webhook_delivery.send_sheet_row.run(tenant_id=tid, guest_id=g.id)
    assert retry.call_args.kwargs["countdown"] == 60
    assert "HTTP 500" in gs.status(gs.get_row(db, tid))["last_error"]
    with _google(403), \
            patch.object(webhook_delivery.send_sheet_row, "retry") as retry:
        webhook_delivery.send_sheet_row.run(tenant_id=tid, guest_id=g.id)
    retry.assert_not_called()
    with _google(200):
        webhook_delivery.send_sheet_row.run(tenant_id=tid, guest_id=g.id)
    st = gs.status(gs.get_row(db, tid))
    assert st["rows_sent"] == 1 and st["last_error"] is None and st["last_sent_at"]
