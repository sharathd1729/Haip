"""HAIP Calls app, step 1 (docs/MOBILE_CALL_TRACKING_SPEC.md): device tokens, settings and call-log upload.

Uploaded calls are queued into call_ingest.process (ivr_provider "mobile_app"); these tests capture the queued payloads and
run the real ingest task on the test's own connection, so the Call rows come from the same code IVR calls use.
"""
import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session as SASession

from app.core.security import create_access_token
from app.models.audit_event import AuditEvent
from app.models.call import Call
from app.models.guest import Guest
from app.models.mobile_device import MobileDevice
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import identity_service
from app.workers.tasks import call_ingest

KNOWN = "+919845612345"
UNKNOWN = "+917249066854"


def _tid(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _user(db, tenant_id, role=UserRole.FOH):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value} user", email=f"{uuid.uuid4().hex[:8]}@t.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return u, _auth(create_access_token({"sub": u.id, "tenant_id": tenant_id, "role": role.value}))


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _register(client, headers, device_id=None, settings=None):
    body = {"device_id": device_id or uuid.uuid4().hex, "model": "Galaxy A54", "android_version": "14", "app_version": "1.0.0"}
    if settings is not None:
        body["settings"] = settings
    r = client.post("/api/v1/devices/register", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _call(number=KNOWN, direction="in", answered=True, duration=42, started="2026-11-12T11:00:00+05:30", cid=None):
    return {"device_call_id": cid or uuid.uuid4().hex[:12], "number": number, "direction": direction,
            "started_at": started, "duration_sec": duration, "answered": answered, "sim_slot": 1}


@pytest.fixture()
def queued(monkeypatch):
    """Captures ingest tasks instead of sending them to Celery."""
    sent = []
    monkeypatch.setattr(call_ingest.ingest_call, "delay", lambda payload, tenant_id, provider: sent.append((payload, tenant_id, provider)))
    return sent


def _run_ingest(monkeypatch, db, sent):
    """Run each queued task with the real ingest code, on the test's connection (see test_call_ingest_direction_fix.py)."""
    fetched = []
    monkeypatch.setattr(call_ingest.fetch_and_store_recording, "delay", lambda **kw: fetched.append(kw))
    monkeypatch.setattr(call_ingest, "SessionLocal", lambda: SASession(bind=db.connection()))
    out = [call_ingest.ingest_call.run(payload=p, tenant_id=t, ivr_provider=prov) for p, t, prov in sent]
    sent.clear()
    assert fetched == []   # nothing to fetch: the device uploads recordings itself (step 2)
    return out


# ─── Registration, token, revoke ─────────────────────────────────────────────

def test_register_returns_token_once_and_stores_only_its_hash(client, db, tenant_and_user):
    out = _register(client, _auth(tenant_and_user["access_token"]))
    token = out["token"]
    assert token.startswith("haip_dev_")
    row = db.query(MobileDevice).filter_by(id=out["id"]).one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(row.settings) and row.user_id == tenant_and_user["user"].id
    assert db.query(AuditEvent).filter_by(target_id=row.id, action="mobile_device.registered").count() == 1
    listed = client.get("/api/v1/devices", headers=_auth(tenant_and_user["access_token"])).json()["devices"]
    assert [d["id"] for d in listed] == [row.id] and "token" not in listed[0]


def test_re_register_same_install_rotates_token_on_same_row(client, db, tenant_and_user, queued):
    headers = _auth(tenant_and_user["access_token"])
    first = _register(client, headers, device_id="install-1")
    second = _register(client, headers, device_id="install-1")
    assert first["id"] == second["id"] and first["token"] != second["token"]
    batch = {"calls": [_call()]}
    assert client.post("/api/v1/device-calls", json=batch, headers=_auth(first["token"])).status_code == 401
    assert client.post("/api/v1/device-calls", json=batch, headers=_auth(second["token"])).status_code == 200


def test_missing_bad_and_revoked_token_are_401(client, db, tenant_and_user, queued):
    batch = {"calls": [_call()]}
    assert client.post("/api/v1/device-calls", json=batch).status_code == 401
    assert client.post("/api/v1/device-calls", json=batch, headers=_auth("haip_dev_nope")).status_code == 401
    out = _register(client, _auth(tenant_and_user["access_token"]))
    assert client.delete(f"/api/v1/devices/{out['id']}", headers=_auth(tenant_and_user["access_token"])).status_code == 204
    assert client.post("/api/v1/device-calls", json=batch, headers=_auth(out["token"])).status_code == 401
    assert db.query(AuditEvent).filter_by(target_id=out["id"], action="mobile_device.revoked").count() == 1
    assert queued == []


def test_deactivated_user_device_is_401(client, db, tenant_and_user, queued):
    staff, staff_h = _user(db, _tid(tenant_and_user))
    out = _register(client, staff_h)
    staff.is_active = False
    db.commit()
    assert client.post("/api/v1/device-calls", json={"calls": [_call()]}, headers=_auth(out["token"])).status_code == 401


def test_staff_cannot_list_or_revoke_others_devices_but_can_revoke_own(client, db, tenant_and_user):
    owner_dev = _register(client, _auth(tenant_and_user["access_token"]))
    _, staff_h = _user(db, _tid(tenant_and_user))
    own = _register(client, staff_h)
    assert client.get("/api/v1/devices", headers=staff_h).status_code == 403
    assert client.delete(f"/api/v1/devices/{owner_dev['id']}", headers=staff_h).status_code == 403
    assert client.delete(f"/api/v1/devices/{own['id']}", headers=staff_h).status_code == 204
    _, manager_h = _user(db, _tid(tenant_and_user), UserRole.MANAGER)
    assert client.delete(f"/api/v1/devices/{owner_dev['id']}", headers=manager_h).status_code == 204


def test_other_tenant_cannot_see_or_revoke_device(client, db, tenant_and_user):
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    other = _other_tenant(db)
    _, other_owner_h = _user(db, other.id, UserRole.OWNER)
    assert client.get("/api/v1/devices", headers=other_owner_h).json()["devices"] == []
    assert client.delete(f"/api/v1/devices/{dev['id']}", headers=other_owner_h).status_code == 404
    assert db.query(MobileDevice).filter_by(id=dev["id"]).one().revoked_at is None


# ─── Call upload ─────────────────────────────────────────────────────────────

def test_known_guest_call_goes_through_ivr_ingest_as_mobile_app(client, db, tenant_and_user, queued, monkeypatch):
    tid = _tid(tenant_and_user)
    guest_id, _ = identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()
    staff, staff_h = _user(db, tid)
    dev = _register(client, staff_h)
    r = client.post("/api/v1/device-calls", json={"calls": [_call(number="09845612345")]}, headers=_auth(dev["token"]))
    assert r.json()["counts"] == {"queued": 1}
    assert queued[0][1] == tid and queued[0][2] == "mobile_app"
    [res] = _run_ingest(monkeypatch, db, queued)
    call = db.query(Call).filter_by(id=res["call_id"]).one()
    assert (call.ivr_provider, call.guest_id, call.agent_id) == ("mobile_app", guest_id, staff.id)
    assert call.direction.value == "inbound" and call.from_number == KNOWN and call.duration_seconds == 42
    assert call.ivr_dial_status == "completed" and call.inquiry_id is not None


def test_resend_is_idempotent(client, db, tenant_and_user, queued, monkeypatch):
    tid = _tid(tenant_and_user)
    identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    c = _call(cid="log-77")
    first = client.post("/api/v1/device-calls", json={"calls": [c, c]}, headers=_auth(dev["token"])).json()
    assert [x["status"] for x in first["results"]] == ["queued", "duplicate"]
    queued.append(queued[0])   # a task delivered twice still makes one call
    assert [r["status"] for r in _run_ingest(monkeypatch, db, queued)] == ["created", "already_exists"]
    again = client.post("/api/v1/device-calls", json={"calls": [c]}, headers=_auth(dev["token"])).json()
    assert again["counts"] == {"duplicate": 1} and queued == []
    assert db.query(Call).filter(Call.tenant_id == tid, Call.ivr_call_id.like(f"mobile_app:{dev['id']}:%")).count() == 1


def test_guest_known_only_by_guest_row_phone_is_matched_not_duplicated(client, db, tenant_and_user, queued, monkeypatch):
    tid = _tid(tenant_and_user)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Mirror chat", phone=UNKNOWN)
    db.add(g)
    db.commit()
    dev = _register(client, _auth(tenant_and_user["access_token"]), settings={"unknown_numbers": "never"})
    r = client.post("/api/v1/device-calls", json={"calls": [_call(number=UNKNOWN)]}, headers=_auth(dev["token"]))
    assert r.json()["counts"] == {"queued": 1}   # known person, so the unknown-number rule does not apply
    [res] = _run_ingest(monkeypatch, db, queued)
    assert db.query(Call).filter_by(id=res["call_id"]).one().guest_id == g.id
    assert db.query(Guest).filter_by(tenant_id=tid, phone=UNKNOWN).count() == 1


def test_guest_in_another_tenant_is_not_matched(client, db, tenant_and_user, queued):
    other = _other_tenant(db)
    identity_service.resolve_gid(db, other.id, "phone", KNOWN, source="test")
    db.commit()
    dev = _register(client, _auth(tenant_and_user["access_token"]), settings={"unknown_numbers": "never"})
    r = client.post("/api/v1/device-calls", json={"calls": [_call(number=KNOWN)]}, headers=_auth(dev["token"]))
    assert r.json()["counts"] == {"skipped_unknown_number": 1} and queued == []


@pytest.mark.parametrize("settings, started, expected", [
    ({"unknown_numbers": "never"}, "2026-11-12T11:00:00+05:30", "skipped_unknown_number"),
    ({"unknown_numbers": "always"}, "2026-11-12T03:00:00+05:30", "queued"),
    ({}, "2026-11-12T03:00:00+05:30", "queued"),   # default, no working hours set: on
    ({"working_hours": {"start": "09:00", "end": "21:00"}}, "2026-11-12T11:00:00+05:30", "queued"),
    ({"working_hours": {"start": "09:00", "end": "21:00"}}, "2026-11-12T22:30:00+05:30", "skipped_unknown_number"),
    # 05:00 UTC = 10:30 in the workspace's Asia/Kolkata: inside 09:00-21:00
    ({"working_hours": {"start": "09:00", "end": "21:00"}}, "2026-11-12T05:00:00+00:00", "queued"),
    ({"working_hours": {"start": "22:00", "end": "06:00"}}, "2026-11-12T23:30:00+05:30", "queued"),   # overnight
    ({"working_hours": {"start": "22:00", "end": "06:00"}}, "2026-11-12T12:00:00+05:30", "skipped_unknown_number"),
])
def test_unknown_number_rule(client, db, tenant_and_user, queued, settings, started, expected):
    dev = _register(client, _auth(tenant_and_user["access_token"]), settings=settings)
    r = client.post("/api/v1/device-calls", json={"calls": [_call(number=UNKNOWN, started=started)]}, headers=_auth(dev["token"]))
    assert r.json()["results"][0]["status"] == expected
    assert len(queued) == (1 if expected == "queued" else 0)


def test_personal_number_is_rejected_and_never_stored(client, db, tenant_and_user, queued):
    tid = _tid(tenant_and_user)
    identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    s = client.put("/api/v1/devices/settings", json={"personal_numbers": ["98456 12345"]}, headers=_auth(dev["token"]))
    assert s.status_code == 200 and s.json()["personal_numbers_count"] == 1
    row = db.query(MobileDevice).filter_by(id=dev["id"]).one()
    assert "9845612345" not in str(row.settings)
    r = client.post("/api/v1/device-calls", json={"calls": [_call(number=KNOWN), _call(number="private")]},
                    headers=_auth(dev["token"]))
    assert [x["status"] for x in r.json()["results"]] == ["rejected_personal", "invalid_number"] and queued == []


def test_batch_over_200_is_rejected(client, db, tenant_and_user, queued):
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    r = client.post("/api/v1/device-calls", json={"calls": [_call() for _ in range(201)]}, headers=_auth(dev["token"]))
    assert r.status_code == 422 and queued == []


def test_missed_inbound_shows_where_ivr_calls_show_and_on_my_day(client, db, tenant_and_user, queued, monkeypatch):
    from app.services import work_queue_service

    tid = _tid(tenant_and_user)
    tenant = db.query(Tenant).filter_by(id=tid).one()
    tenant.ivr_provider = "vobiz"   # the tenant's IVR is something else; Calls app calls still show
    guest_id, _ = identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    started = datetime.now(timezone.utc).isoformat()
    client.post("/api/v1/device-calls", json={"calls": [_call(answered=False, duration=12, started=started)]},
                headers=_auth(dev["token"]))
    [res] = _run_ingest(monkeypatch, db, queued)
    missed = client.get("/api/v1/calls?missed=true", headers=_auth(tenant_and_user["access_token"])).json()
    assert res["call_id"] in str(missed)
    assert guest_id in [i.guest_id for i in work_queue_service._callbacks(db, tenant)]


def test_unanswered_outbound_is_an_attempt_with_callback_task(client, db, tenant_and_user, queued, monkeypatch):
    from app.services import call_status_service

    tid = _tid(tenant_and_user)
    guest_id, _ = identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()
    staff, staff_h = _user(db, tid)
    dev = _register(client, staff_h)
    client.post("/api/v1/device-calls", json={"calls": [_call(direction="out", answered=False, duration=25)]},
                headers=_auth(dev["token"]))
    [res] = _run_ingest(monkeypatch, db, queued)
    call = db.query(Call).filter_by(id=res["call_id"]).one()
    assert call.to_number == KNOWN and call.duration_seconds == 0
    assert call_status_service.is_unanswered_outbound(call)
    task = db.query(Task).filter_by(tenant_id=tid, guest_id=guest_id, is_done=False).one()
    assert task.title.startswith("Call back — no answer") and task.assigned_to == staff.id
