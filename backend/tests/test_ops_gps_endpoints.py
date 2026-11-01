"""Ops GPS API + push webhook: happy paths, wrong role, cross-tenant."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.adapters.gps import webhook
from app.core.encryption import decrypt_credentials
from app.models.audit_event import AuditEvent
from app.models.gps import GpsDevice
from app.models.integration import Integration
from app.models.user import UserRole
from app.services import gps_ingest
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, tenant
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_gps import OFF, P, _device, _trip


def _world(db):
    t = tenant(db)
    seed_capabilities(db, t.id)
    p = prop(db, t.id, "Ratha 1")
    return type(
        "W",
        (),
        {
            "t": t,
            "p": p,
            "f": _trip(db, t, p),
            "d": _device(db, t, p),
            "owner": _user(db, t.id, UserRole.OWNER),
            "mgr": _user(db, t.id, UserRole.MANAGER),
            "foh": _user(db, t.id, UserRole.FOH),
            "mkt": _user(db, t.id, UserRole.MARKETING),
        },
    )()


@pytest.fixture()
def w(db):
    return _world(db)


@pytest.fixture()
def other(db):
    return _world(db)


@pytest.fixture(autouse=True)
def _no_celery():
    with patch("app.workers.tasks.gps.ingest.delay") as q:
        yield q


def test_webhook_settings_show_the_secret_once_and_audit_without_it(client, db, w):
    r = client.put("/api/v1/ops/gps/settings", json={"provider": "webhook"}, headers=_h(w.mgr))
    assert r.status_code == 200, r.text
    secret = r.json()["webhook_secret"]
    assert secret and r.json()["webhook_url"].endswith(f"/api/v1/webhooks/gps/{w.t.slug}")
    again = client.get("/api/v1/ops/gps/settings", headers=_h(w.mgr)).json()
    assert "webhook_secret" not in again and again["has_webhook_secret"] is True
    assert (
        client.put("/api/v1/ops/gps/settings", json={"provider": "webhook"}, headers=_h(w.mgr)).json()["webhook_secret"]
        is None
    )
    row = db.query(Integration).filter_by(tenant_id=w.t.id, kind="gps").one()
    assert decrypt_credentials(row.credentials_kms_blob)["webhook_secret"] == secret
    audits = db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ops.gps.connection_saved").all()
    assert len(audits) == 2 and all(secret not in json.dumps(a.payload) for a in audits)
    rotated = client.post("/api/v1/ops/gps/settings/rotate-secret", headers=_h(w.owner)).json()["webhook_secret"]
    assert rotated and rotated != secret


def test_settings_need_ops_manage_and_the_custom_app_waits(client, w):
    assert client.put("/api/v1/ops/gps/settings", json={"provider": "webhook"}, headers=_h(w.foh)).status_code == 403
    assert client.get("/api/v1/ops/gps/settings", headers=_h(w.foh)).status_code == 403
    r = client.put("/api/v1/ops/gps/settings", json={"provider": "custom_http"}, headers=_h(w.owner))
    assert r.status_code == 422 and "API details" in r.json()["detail"]
    r = client.put(
        "/api/v1/ops/gps/settings",
        json={"provider": "traccar", "base_url": "http://10.0.0.5", "password": "x"},
        headers=_h(w.owner),
    )
    assert r.status_code == 422


def test_traccar_password_is_never_returned(client, db, w):
    with patch("app.services.gps_service.assert_public_url"):
        r = client.put(
            "/api/v1/ops/gps/settings",
            headers=_h(w.owner),
            json={
                "provider": "traccar",
                "base_url": "https://traccar.example.com/",
                "username": "ops",
                "password": "pw-123",
                "rules": {"overspeed_kmh": 65},
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pw-123" not in r.text and body["has_password"] and body["base_url"] == "https://traccar.example.com"
    assert body["rules"]["overspeed_kmh"] == 65 and body["rules"]["off_route_km"] == 1.5


def test_devices_crud_and_cross_tenant(client, db, w, other):
    r = client.post(
        "/api/v1/ops/gps/devices",
        headers=_h(w.mgr),
        json={"external_id": " 8612 ", "label": "White Ratha", "property_id": w.p.id},
    )
    assert r.status_code == 201 and r.json()["external_id"] == "8612"
    dev_id = r.json()["id"]
    assert client.post("/api/v1/ops/gps/devices", headers=_h(w.mgr), json={"external_id": "8612"}).status_code == 409
    assert (
        client.post(
            "/api/v1/ops/gps/devices", headers=_h(w.mgr), json={"external_id": "9", "property_id": other.p.id}
        ).status_code
        == 422
    )  # their vehicle
    assert client.post("/api/v1/ops/gps/devices", headers=_h(w.foh), json={"external_id": "9"}).status_code == 403
    assert (
        client.patch(f"/api/v1/ops/gps/devices/{dev_id}", headers=_h(other.owner), json={"active": False}).status_code
        == 404
    )
    assert (
        client.patch(f"/api/v1/ops/gps/devices/{dev_id}", headers=_h(w.mgr), json={"active": False}).json()["active"]
        is False
    )
    ids = [d["id"] for d in client.get("/api/v1/ops/gps/devices", headers=_h(w.foh)).json()]
    assert dev_id in ids and other.d.id not in ids
    assert client.delete(f"/api/v1/ops/gps/devices/{dev_id}", headers=_h(other.owner)).status_code == 404
    assert client.delete(f"/api/v1/ops/gps/devices/{dev_id}", headers=_h(w.mgr)).status_code == 204
    assert (
        db.query(AuditEvent).filter(AuditEvent.tenant_id == w.t.id, AuditEvent.action.like("ops.gps.device_%")).count()
        == 3
    )


def test_live_map_shows_position_trip_and_alerts(client, db, w, other):
    gps_ingest.ingest(db, w.t.id, "webhook", [P("IMEI1", m, lng=OFF) for m in range(3)], now=P("IMEI1", 3).at)
    db.commit()
    r = client.get("/api/v1/ops/gps/live", headers=_h(w.foh))
    assert r.status_code == 200
    (v,) = r.json()["vehicles"]
    assert v["name"] == "Ratha 1" and v["file_id"] == w.f.id and v["lng"] == OFF
    assert v["alerts"][0]["kind"] == "gps_off_route"
    assert client.get("/api/v1/ops/gps/live", headers=_h(w.mkt)).status_code == 403
    assert [
        x["property_id"] for x in client.get("/api/v1/ops/gps/live", headers=_h(other.owner)).json()["vehicles"]
    ] == [other.p.id]


def test_track_route_and_detour_endpoints(client, db, w, other):
    route = {"points": [{"lat": 12.9, "lng": 77.6}, {"lat": 13.3, "lng": 77.6, "stop": True}], "night_driving_ok": True}
    assert client.put(f"/api/v1/ops/gps/files/{w.f.id}/route", json=route, headers=_h(w.foh)).status_code == 403
    assert client.put(f"/api/v1/ops/gps/files/{w.f.id}/route", json=route, headers=_h(other.owner)).status_code == 404
    r = client.put(f"/api/v1/ops/gps/files/{w.f.id}/route", json=route, headers=_h(w.mgr))
    assert r.status_code == 200 and r.json()["planned_route"]["night_driving_ok"] is True
    assert client.get(f"/api/v1/ops/gps/files/{w.f.id}/track", headers=_h(other.owner)).status_code == 404
    gps_ingest.ingest(db, w.t.id, "webhook", [P("IMEI1", m, lng=OFF) for m in range(3)], now=P("IMEI1", 3).at)
    db.commit()
    item_id = client.get("/api/v1/ops/gps/live", headers=_h(w.mgr)).json()["vehicles"][0]["alerts"][0]["id"]
    url = f"/api/v1/ops/gps/alerts/{item_id}/approve-detour"
    assert client.post(url, json={"reason": "Diversion"}, headers=_h(w.foh)).status_code == 403
    assert client.post(url, json={"reason": "Diversion"}, headers=_h(other.owner)).status_code == 404
    r = client.post(url, json={"reason": "Diversion"}, headers=_h(w.mgr))
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert client.get(f"/api/v1/ops/gps/files/{w.f.id}/track", headers=_h(w.foh)).json()["planned_route"]["detours"]


def test_push_webhook_checks_signature_and_queues(client, db, w, _no_celery):
    secret = client.put("/api/v1/ops/gps/settings", json={"provider": "webhook"}, headers=_h(w.mgr)).json()[
        "webhook_secret"
    ]
    now = datetime.now(UTC)
    body = json.dumps(
        {
            "positions": [
                {
                    "device_id": "IMEI1",
                    "time": (now - timedelta(seconds=30)).isoformat(),
                    "lat": 12.97,
                    "lng": 77.59,
                    "speed_kmh": 40,
                }
            ]
        }
    ).encode()
    ts = int(now.timestamp())
    good = {
        "X-HAIP-Timestamp": str(ts),
        "X-HAIP-Signature": webhook.sign(body, secret, ts),
        "Content-Type": "application/json",
    }
    r = client.post(f"/api/v1/webhooks/gps/{w.t.slug}", content=body, headers=good)
    assert r.status_code == 200 and r.json()["accepted"] == 1
    (tenant_id, provider, rows), _ = _no_celery.call_args
    assert tenant_id == w.t.id and provider == "webhook" and rows[0]["device_id"] == "IMEI1"
    bad = {**good, "X-HAIP-Signature": webhook.sign(body, "wrong", ts)}
    assert client.post(f"/api/v1/webhooks/gps/{w.t.slug}", content=body, headers=bad).status_code == 401
    assert client.post("/api/v1/webhooks/gps/no-such-business", content=body, headers=good).status_code == 404


def test_push_signed_for_one_business_is_refused_by_another(client, db, w, other):
    secret = client.put("/api/v1/ops/gps/settings", json={"provider": "webhook"}, headers=_h(w.mgr)).json()[
        "webhook_secret"
    ]
    client.put("/api/v1/ops/gps/settings", json={"provider": "webhook"}, headers=_h(other.mgr))
    body = json.dumps({"positions": []}).encode()
    ts = int(datetime.now(UTC).timestamp())
    h = {"X-HAIP-Timestamp": str(ts), "X-HAIP-Signature": webhook.sign(body, secret, ts)}
    assert client.post(f"/api/v1/webhooks/gps/{other.t.slug}", content=body, headers=h).status_code == 401
    assert db.query(GpsDevice).filter_by(tenant_id=other.t.id).count() == 1
