"""Ops GPS (migration 181): adapters, ingest, every alert rule ("lasts long enough", "fires once"), detours, purge."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.adapters import gps as adapters
from app.adapters.gps import traccar, webhook
from app.models.audit_event import AuditEvent
from app.models.gps import GpsAlertEpisode, GpsDevice, GpsPosition
from app.models.guest import Guest
from app.models.ops import OpsItem
from app.models.ops_files import OpsFile, OpsFileEvent
from app.models.property import Stay
from app.schemas.gps import RouteIn
from app.services import gps_alerts, gps_geo, gps_ingest, gps_service
from tests.ops_helpers import ist, prop, tenant

T0 = ist(2026, 10, 27, 10, 0)  # a Tuesday morning, IST
ON = 77.60  # the planned road runs north along this longitude
OFF = 77.65  # ~5.4 km east of it


def P(dev, minutes, lat=13.0, lng=ON, speed=50.0, ignition=True, odo=None):
    return adapters.Position(
        device_id=dev,
        at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lng=lng,
        speed_kmh=speed,
        ignition=ignition,
        odometer_km=odo,
        provider="webhook",
    )


def _trip(db, t, p, route=True, night_ok=False):
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Sample Guest", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    s = Stay(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        guest_id=g.id,
        property_id=p.id,
        check_in=date(2026, 10, 27),
        check_out=date(2026, 10, 30),
        adults=4,
        children=0,
        status="confirmed",
        total_amount=Decimal("100000"),
    )
    db.add(s)
    db.flush()  # PostgreSQL checks the foreign keys: the stay goes in before its file
    f = OpsFile(
        tenant_id=t.id,
        stay_id=s.id,
        pack="caravan_rv",
        state="on_trip",
        dispatched_at=T0 - timedelta(hours=1),
        details={"start_odometer": 1000, "end_odometer": 1050},
    )
    if route:
        f.gps_route = {
            "points": [
                {"lat": 12.9, "lng": ON, "stop": False},
                {"lat": 13.1, "lng": ON, "stop": True},
                {"lat": 13.3, "lng": ON, "stop": False},
            ],
            "night_driving_ok": night_ok,
            "detours": [],
        }
    db.add(f)
    db.commit()
    return f


def _device(db, t, p, ext="IMEI1", provider="webhook"):
    d = GpsDevice(tenant_id=t.id, provider=provider, external_id=ext, property_id=p.id, active=True)
    db.add(d)
    db.commit()
    return d


@pytest.fixture()
def w(db):
    t = tenant(db)
    p = prop(db, t.id, "Ratha 1")
    return type("W", (), {"t": t, "p": p, "f": _trip(db, t, p), "d": _device(db, t, p)})()


def _feed(db, w, *positions, now=None):
    out = gps_ingest.ingest(db, w.t.id, "webhook", list(positions), now=now or positions[-1].at)
    db.commit()
    return out


def _items(db, w, kind=None):
    q = db.query(OpsItem).filter(OpsItem.tenant_id == w.t.id, OpsItem.category == "gps")
    return q.filter(OpsItem.kind == kind).all() if kind else q.all()


# ── Adapters ───────────────────────────────────────────────────────────────

FIXTURE = {
    "positions": [
        {
            "device_id": "861234567890123",
            "time": "2026-10-28T10:15:00Z",
            "lat": 12.9716,
            "lng": 77.5946,
            "speed_kmh": 54.2,
            "heading": 180,
            "ignition": True,
            "odometer_km": 87412.5,
        },
        {"device_id": "861234567890123", "time": 1793182560, "lat": 12.98, "lng": 77.6},
        {"device_id": "861234567890123", "time": "2026-10-28T10:16:00Z", "lat": 0, "lng": 0},  # no fix: skipped
        {"device_id": "", "time": "2026-10-28T10:16:00Z", "lat": 12.9, "lng": 77.5},  # no device: skipped
        {"device_id": "x", "time": "2026-10-28T10:16:00", "lat": 12.9, "lng": 77.5},  # no zone: skipped
    ]
}
NOW = datetime(2026, 10, 28, 10, 17, tzinfo=UTC)


def _signed(body: bytes, secret="s3cret", ts=None):
    ts = int((ts or NOW).timestamp())
    return {"X-HAIP-Timestamp": str(ts), "X-HAIP-Signature": webhook.sign(body, secret, ts)}


def test_webhook_signature_good_reads_the_fixture():
    body = json.dumps(FIXTURE).encode()
    out = adapters.parse_push(adapters.PROVIDERS["webhook"], body, _signed(body), "s3cret", now=NOW)
    assert len(out) == 2
    a = out[0]
    assert (a.device_id, a.lat, a.speed_kmh, a.ignition, a.odometer_km, a.provider) == (
        "861234567890123",
        12.9716,
        54.2,
        True,
        87412.5,
        "webhook",
    )
    assert a.at == datetime(2026, 10, 28, 10, 15, tzinfo=UTC) and out[1].at.tzinfo is not None


def test_webhook_bad_signature_and_old_request_are_refused():
    body = json.dumps(FIXTURE).encode()
    with pytest.raises(adapters.GpsAuthError):
        adapters.parse_push(adapters.PROVIDERS["webhook"], body, _signed(body, "other"), "s3cret", now=NOW)
    with pytest.raises(adapters.GpsAuthError):  # body changed after signing
        adapters.parse_push(adapters.PROVIDERS["webhook"], body + b" ", _signed(body), "s3cret", now=NOW)
    with pytest.raises(adapters.GpsAuthError):  # signed 6 minutes ago: replay window passed
        adapters.parse_push(
            adapters.PROVIDERS["webhook"], body, _signed(body, ts=NOW - timedelta(minutes=6)), "s3cret", now=NOW
        )
    with pytest.raises(adapters.GpsAuthError):  # no secret set = nothing accepted
        adapters.parse_push(adapters.PROVIDERS["webhook"], body, _signed(body), "", now=NOW)
    with pytest.raises(adapters.GpsPayloadError):
        adapters.parse_push(adapters.PROVIDERS["webhook"], b"[]", _signed(b"[]"), "s3cret", now=NOW)


def test_traccar_parsing_converts_knots_and_metres():
    p = traccar.parse_position(
        {
            "deviceId": 7,
            "fixTime": "2026-10-28T10:15:00.000+00:00",
            "latitude": 12.9,
            "longitude": 77.6,
            "speed": 10.0,
            "course": 90,
            "attributes": {"ignition": True, "odometer": 87412500},
        },
        "IMEI9",
    )
    assert (p.device_id, p.speed_kmh, p.odometer_km, p.ignition, p.heading) == ("IMEI9", 18.5, 87412.5, True, 90.0)


def test_traccar_fetch_uses_devices_then_positions(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        if req.url.path == "/api/devices":
            return httpx.Response(
                200, json=[{"id": 7, "uniqueId": "IMEI9"}, {"id": 8, "uniqueId": "OFF", "disabled": True}]
            )
        return httpx.Response(
            200,
            json=[
                {"deviceId": 7, "fixTime": "2026-10-28T10:15:00Z", "latitude": 12.9, "longitude": 77.6, "speed": 0},
                {"deviceId": 7, "fixTime": "2026-10-28T10:16:00Z", "latitude": 12.9, "longitude": 77.6, "valid": False},
            ],
        )

    real = httpx.Client
    monkeypatch.setattr(traccar.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(traccar, "assert_public_url", lambda url, allow_http=False: None)
    out = traccar.fetch_positions(
        {"base_url": "https://t.example.com", "username": "u"}, {"password": "p"}, {}, now=NOW
    )
    assert [p.device_id for p in out] == ["IMEI9"] and seen == ["/api/devices", "/api/positions"]


def test_traccar_refuses_internal_or_plain_http_addresses():
    for url in ("http://t.example.com", "https://127.0.0.1"):
        with pytest.raises(adapters.GpsFetchError):
            traccar.fetch_positions({"base_url": url}, {"password": "p"}, {}, now=NOW)


def test_custom_app_slot_is_not_enabled_yet():
    with pytest.raises(adapters.GpsProviderBlocked):
        adapters.get_provider("custom_http")


# ── Ingest ─────────────────────────────────────────────────────────────────


def test_ingest_is_idempotent_and_unknown_trackers_wait_for_a_vehicle(db, w):
    first = _feed(db, w, P("IMEI1", 0), P("IMEI1", 1), P("NEW", 1))
    again = _feed(db, w, P("IMEI1", 1))
    assert (first["stored"], first["new_devices"], again["duplicates"]) == (2, 1, 1)
    new = db.query(GpsDevice).filter_by(tenant_id=w.t.id, external_id="NEW").one()
    assert new.active is False and new.property_id is None and new.last_lat == 13.0
    assert db.query(GpsPosition).filter_by(device_id=new.id).count() == 0
    rows = db.query(GpsPosition).filter_by(device_id=w.d.id).all()
    assert len(rows) == 2 and all(r.file_id == w.f.id for r in rows)


def test_a_fix_never_lands_on_another_business_vehicle(db, w):
    other_t = tenant(db)
    other_p = prop(db, other_t.id, "Other van")
    other_d = _device(db, other_t, other_p, ext="IMEI1")  # same tracker id in another business
    _feed(db, w, P("IMEI1", 0))
    assert db.query(GpsPosition).filter_by(device_id=other_d.id).count() == 0
    assert db.query(GpsPosition).filter_by(tenant_id=other_t.id).count() == 0
    assert db.get(GpsDevice, other_d.id).last_seen_at is None


# ── Rules ──────────────────────────────────────────────────────────────────


def test_off_route_needs_three_fixes_in_a_row_and_fires_once(db, w):
    _feed(db, w, P("IMEI1", 0, lng=OFF), P("IMEI1", 1, lng=OFF))
    assert _items(db, w) == []  # two bad fixes: not yet
    _feed(db, w, P("IMEI1", 2, lng=OFF))
    assert len(_items(db, w, "gps_off_route")) == 1
    _feed(db, w, P("IMEI1", 3, lng=OFF))
    assert len(_items(db, w, "gps_off_route")) == 1  # same episode: no second alert
    it = _items(db, w, "gps_off_route")[0]
    assert it.severity == "high" and it.duty == "ops_manager" and "openstreetmap.org" in it.summary
    assert it.stay_id == db.get(OpsFile, w.f.id).stay_id
    _feed(db, w, P("IMEI1", 4))  # back on the road: episode over
    _feed(db, w, *(P("IMEI1", m, lng=OFF) for m in (5, 6, 7)))
    assert len(_items(db, w, "gps_off_route")) == 2  # a new episode fires again


def test_off_route_by_time_and_only_with_a_route(db, w):
    _feed(db, w, P("IMEI1", 0, lng=OFF), P("IMEI1", 6, lng=OFF))  # two fixes, six minutes apart
    assert len(_items(db, w, "gps_off_route")) == 1
    p2 = prop(db, w.t.id, "Ratha 2")
    _trip(db, w.t, p2, route=False)
    _device(db, w.t, p2, ext="IMEI2")
    _feed(db, w, *(P("IMEI2", m, lng=OFF) for m in range(5)))
    assert len(_items(db, w, "gps_off_route")) == 1  # no route = no route check


def test_halt_away_from_a_stop_after_30_minutes(db, w):
    _feed(db, w, P("IMEI1", 0, lat=13.2, speed=0), P("IMEI1", 20, lat=13.2, speed=0))
    assert _items(db, w, "gps_halt") == []
    _feed(db, w, P("IMEI1", 31, lat=13.2, speed=0))
    assert len(_items(db, w, "gps_halt")) == 1 and _items(db, w, "gps_halt")[0].severity == "normal"


def test_halt_at_a_planned_stop_is_fine_and_tick_fires_a_halt_with_no_new_fix(db, w):
    _feed(db, w, P("IMEI1", 0, lat=13.1, speed=0), P("IMEI1", 40, lat=13.1, speed=0))  # at the planned stop
    assert _items(db, w, "gps_halt") == []
    _feed(db, w, P("IMEI1", 41, lat=13.25, speed=0, ignition=False))  # parks elsewhere, tracker goes to sleep
    gps_alerts.tick(db, w.t.id, now=T0 + timedelta(minutes=70))  # 29 min: not yet
    assert _items(db, w, "gps_halt") == []
    gps_alerts.tick(db, w.t.id, now=T0 + timedelta(minutes=72))
    db.commit()
    gps_alerts.tick(db, w.t.id, now=T0 + timedelta(minutes=73))
    db.commit()
    assert len(_items(db, w, "gps_halt")) == 1


def test_overspeed_must_last_over_a_minute(db, w):
    _feed(db, w, P("IMEI1", 0, speed=75), P("IMEI1", 0.5, speed=78))
    assert _items(db, w, "gps_overspeed") == []
    _feed(db, w, P("IMEI1", 1.2, speed=80), P("IMEI1", 2, speed=82))
    items = _items(db, w, "gps_overspeed")
    assert len(items) == 1 and "80 km/h" in items[0].summary  # worst so far when it fired


def test_night_driving_and_the_route_can_allow_it(db, w):
    night = ist(2026, 10, 27, 23, 30)
    mins = [(night - T0).total_seconds() / 60 + m for m in (0, 1, 3)]
    _feed(db, w, *(P("IMEI1", m) for m in mins))
    assert len(_items(db, w, "gps_night")) == 1 and _items(db, w, "gps_night")[0].severity == "high"
    p2 = prop(db, w.t.id, "Ratha 2")
    _trip(db, w.t, p2, night_ok=True)
    _device(db, w.t, p2, ext="IMEI2")
    _feed(db, w, *(P("IMEI2", m) for m in mins))
    assert len(_items(db, w, "gps_night")) == 1


def test_tracker_silent_with_ignition_on_fires_once(db, w):
    _feed(db, w, P("IMEI1", 0))
    gps_alerts.tick(db, w.t.id, now=T0 + timedelta(minutes=10))
    assert _items(db, w, "gps_silent") == []
    for m in (16, 17):
        gps_alerts.tick(db, w.t.id, now=T0 + timedelta(minutes=m))
        db.commit()
    assert len(_items(db, w, "gps_silent")) == 1
    _feed(db, w, P("IMEI1", 18))  # it talks again: episode over
    ep = db.query(GpsAlertEpisode).filter_by(file_id=w.f.id, rule="silent").one()
    assert ep.ended_at is not None


def test_tracker_silent_with_ignition_off_is_parked_not_silent(db, w):
    _feed(db, w, P("IMEI1", 0, speed=0, ignition=False))
    gps_alerts.tick(db, w.t.id, now=T0 + timedelta(minutes=40))
    assert _items(db, w, "gps_silent") == []


def test_approved_detour_widens_the_corridor_and_logs_the_reason(db, w):
    _feed(db, w, *(P("IMEI1", m, lat=13.0 + m / 100, lng=OFF) for m in range(3)))
    item = _items(db, w, "gps_off_route")[0]
    gps_alerts.approve_detour(db, w.t.id, item.id, "Road closed at Hosur, police diversion", "u1")
    db.commit()
    assert db.get(OpsItem, item.id).status == "resolved"
    f = db.get(OpsFile, w.f.id)
    assert f.gps_route["detours"][0]["open"] is True and len(f.gps_route["detours"][0]["points"]) == 3
    assert (
        db.query(OpsFileEvent)
        .filter(OpsFileEvent.file_id == f.id, OpsFileEvent.text.contains("Road closed at Hosur"))
        .count()
        == 1
    )
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ops.gps.detour_approved").count() == 1
    _feed(db, w, *(P("IMEI1", m, lat=13.0 + m / 100, lng=OFF) for m in range(3, 9)))  # keeps driving the detour
    assert len(_items(db, w, "gps_off_route")) == 1
    _feed(db, w, P("IMEI1", 10, lat=13.1))  # back on the planned road: detour closed
    f = db.get(OpsFile, w.f.id)
    assert f.gps_route["detours"][0]["open"] is False and len(f.gps_route["detours"][0]["points"]) == 9
    _feed(db, w, *(P("IMEI1", m, lat=13.04, lng=OFF) for m in (11, 12, 13)))  # back along the approved detour: fine
    assert len(_items(db, w, "gps_off_route")) == 1


def test_only_off_route_alerts_can_be_a_detour(db, w):
    _feed(db, w, P("IMEI1", 0, speed=80), P("IMEI1", 2, speed=80))
    with pytest.raises(Exception) as e:
        gps_alerts.approve_detour(db, w.t.id, _items(db, w, "gps_overspeed")[0].id, "ok", "u1")
    assert getattr(e.value, "status_code", None) == 409


def test_alerts_stop_when_the_trip_is_not_on_the_road(db, w):
    f = db.get(OpsFile, w.f.id)
    f.state = "returned"
    db.commit()
    _feed(db, w, *(P("IMEI1", m, lng=OFF, speed=90) for m in range(5)))
    assert _items(db, w) == []


def test_purge_keeps_90_days(db, w):
    _feed(db, w, P("IMEI1", 0), P("IMEI1", 1))
    old = db.query(GpsPosition).filter_by(device_id=w.d.id).order_by(GpsPosition.at).first()
    old.at = T0 - timedelta(days=91)
    db.commit()
    assert gps_ingest.purge(db, w.t.id, now=T0) == 1
    db.commit()
    assert db.query(GpsPosition).filter_by(device_id=w.d.id).count() == 1


def test_track_reports_gps_km_beside_the_odometer(db, w):
    _feed(
        db,
        w,
        P("IMEI1", 0, lat=12.9, odo=500.0),
        P("IMEI1", 10, lat=13.0, odo=511.2),
        P("IMEI1", 11, lat=20.0, odo=511.4),  # a jump no van can make: ignored
        P("IMEI1", 20, lat=13.1, odo=522.3),
    )
    out = gps_service.track(db, w.t.id, w.f.id)
    assert out["odometer_km"] == 50 and out["tracker_odometer_km"] == 22.3
    assert 21.5 < out["gps_km"] < 23 and len(out["points"]) == 4


def test_geo_distance_to_a_line():
    assert gps_geo.distance_to_line_km((13.0, OFF), [(12.9, ON), (13.3, ON)]) == pytest.approx(5.42, abs=0.05)
    assert gps_geo.distance_to_line_km((13.0, ON), [(12.9, ON), (13.3, ON)]) == pytest.approx(0, abs=0.01)


def test_route_body_needs_two_points():
    with pytest.raises(ValueError):
        RouteIn(points=[{"lat": 12.9, "lng": 77.6}])
