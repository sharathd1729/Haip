"""Calls app reliability (backend step 2b): per-device rate limit, re-queue of phone calls whose ingest task was lost,
re-queue of transcriptions stuck "queued", and transcribe skipping a call that is already done."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as SASession

from app.middleware import rate_limit
from app.models.call import Call, CallDirection, RecordingStatus
from app.models.mobile_device import MobileCallPending
from app.workers.tasks import call_recovery, mobile_calls
from tests.test_mobile_devices import KNOWN, _call, _other_tenant, _register, _run_ingest, _tid, _user, queued  # noqa: F401

LATER = datetime.now(timezone.utc) + timedelta(hours=1)


def _auth(dev):
    return {"Authorization": f"Bearer {dev['token']}"}


def _known_guest(db, tid):
    from app.services import identity_service

    identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()


# ─── Rate limit: per device token ────────────────────────────────────────────


def test_device_uploads_are_limited_per_token_not_per_ip(client, db, tenant_and_user, queued, monkeypatch):
    keys = []

    def record(r, key, *a, **k):
        keys.append(key)
        return True, 0

    monkeypatch.setattr(rate_limit, "_check_limit", record)
    tid = _tid(tenant_and_user)
    _, staff_h = _user(db, tid)
    a, b = _register(client, staff_h), _register(client, staff_h)
    for dev in (a, b):  # same test client = same IP
        client.post("/api/v1/device-calls", json={"calls": [_call()]}, headers=_auth(dev))
    device_keys = [k for k in keys if k.startswith("rl:device:")]
    assert len(device_keys) == 2 and device_keys[0] != device_keys[1] and a["token"] not in device_keys[0]
    assert not any(k.endswith(":unauth") for k in keys)


def test_device_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "_check_limit", lambda r, key, *a, **k: (not key.startswith("rl:device:"), 30))
    r = client.post("/api/v1/device-calls", json={"calls": []}, headers={"Authorization": "Bearer haip_dev_x"})
    assert r.status_code == 429 and r.headers.get("retry-after") == "30"


# ─── Phone calls whose ingest task was lost ──────────────────────────────────


def _queued_call(client, db, tenant_and_user, queued):
    tid = _tid(tenant_and_user)
    _known_guest(db, tid)
    _, staff_h = _user(db, tid)
    dev = _register(client, staff_h)
    r = client.post("/api/v1/device-calls", json={"calls": [_call()]}, headers=_auth(dev))
    assert r.json()["counts"] == {"queued": 1}, r.text
    [(payload, _, _)] = queued
    return tid, payload


def test_lost_ingest_is_queued_again_with_the_same_payload(client, db, tenant_and_user, queued):
    tid, payload = _queued_call(client, db, tenant_and_user, queued)
    row = db.query(MobileCallPending).filter_by(tenant_id=tid).one()
    assert row.payload == payload and row.requeue_attempts == 0
    sent = []
    assert mobile_calls.requeue_stuck(db, tid, sent.append) == 0  # too soon: ingest may still be running
    assert mobile_calls.requeue_stuck(db, tid, sent.append, now=LATER) == 1
    db.commit()
    assert sent == [payload] and row.requeue_attempts == 1
    assert mobile_calls.requeue_stuck(db, tid, sent.append, now=LATER) == 0  # spaced REQUEUE_AFTER apart


def test_requeue_counts_only_sent_stops_at_the_cap_and_ingest_clears_it(client, db, tenant_and_user, queued, monkeypatch):
    tid, payload = _queued_call(client, db, tenant_and_user, queued)
    row = db.query(MobileCallPending).filter_by(tenant_id=tid).one()

    def broker_down(p):
        raise ConnectionError("broker down")

    assert mobile_calls.requeue_stuck(db, tid, broker_down, now=LATER) == 0 and row.requeue_attempts == 0
    row.requeue_attempts = mobile_calls.MAX_REQUEUES
    db.commit()
    assert mobile_calls.requeue_stuck(db, tid, lambda p: None, now=LATER) == 0
    _run_ingest(monkeypatch, db, [(payload, tid, "mobile_app")])  # the original task ran after all
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).count() == 0


def test_requeue_never_touches_another_workspace(client, db, tenant_and_user, queued):
    tid, _ = _queued_call(client, db, tenant_and_user, queued)
    other = _other_tenant(db)
    sent = []
    assert mobile_calls.requeue_stuck(db, other.id, sent.append, now=LATER) == 0 and sent == []
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).one().requeue_attempts == 0


# ─── Transcriptions stuck "queued" (any provider) ────────────────────────────


def _stuck_call(db, tenant_id, minutes_ago=45, status="queued"):
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    c = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, ivr_provider="vobiz", ivr_call_id=f"t-{uuid.uuid4().hex[:10]}",
        direction=CallDirection.INBOUND, from_number="+919800000001", to_number="+912200000000",
        started_at=when.isoformat(), duration_seconds=90, recording_s3_key=f"{tenant_id}/calls/x.mp3",
        recording_status=RecordingStatus.AVAILABLE, transcription_status=status, created_at=when, updated_at=when,
    )
    db.add(c)
    db.commit()
    return c


def test_transcription_stuck_queued_is_queued_again_once_per_window(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    stuck, fresh, done = _stuck_call(db, tid), _stuck_call(db, tid, minutes_ago=5), _stuck_call(db, tid, status="done")
    sent = []
    assert call_recovery.requeue_queued_transcriptions(db, tid, sent.append) == 1
    db.commit()
    assert sent == [stuck] and fresh not in sent and done not in sent
    assert call_recovery.requeue_queued_transcriptions(db, tid, sent.append) == 0  # its clock restarted


def test_transcription_requeue_stays_in_its_workspace(db, tenant_and_user):
    _stuck_call(db, _tid(tenant_and_user))
    other = _other_tenant(db)
    sent = []
    assert call_recovery.requeue_queued_transcriptions(db, other.id, sent.append) == 0 and sent == []


def test_transcribe_skips_a_call_that_is_already_done(db, tenant_and_user, monkeypatch):
    from app.workers.tasks import transcribe

    done = _stuck_call(db, _tid(tenant_and_user), status="done")
    monkeypatch.setattr(transcribe, "SessionLocal", lambda: SASession(bind=db.connection()))
    transcribe.transcribe.run(call_id=done.id, tenant_id=done.tenant_id)  # would fail fetching x.mp3 if it went on
    db.refresh(done)
    assert done.transcription_status == "done"
