"""HAIP Calls app, step 2 (docs/MOBILE_CALL_TRACKING_SPEC.md): POST /device-calls/{device_call_id}/recording.

Storage is captured (media_storage.upload_call_recording) and so is the transcription dispatch (tasks.transcribe.delay);
calls are made by the real call_ingest task on the test's connection, as in test_mobile_devices.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.call import Call, RecordingStatus
from app.models.mobile_device import MobileCallPending
from app.services import identity_service, media_storage, mobile_device_service
from app.services.mobile_device_service import sniff_audio
from tests.test_mobile_devices import KNOWN, UNKNOWN, _auth, _call, _other_tenant, _register, _run_ingest, _tid, _user, queued  # noqa: F401

M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 200
SAMPLES = {
    "m4a": (M4A, "audio/mp4"),
    "3gp": (b"\x00\x00\x00\x18ftyp3gp4" + b"\x00" * 64, "audio/mp4"),
    "mp3_id3": (b"ID3\x04\x00\x00" + b"\x00" * 64, "audio/mpeg"),
    "mp3_frame": (b"\xff\xfb\x90\x64" + b"\x00" * 64, "audio/mpeg"),
    "amr": (b"#!AMR\n" + b"\x00" * 64, "audio/amr"),
    "amr_wb": (b"#!AMR-WB\n" + b"\x00" * 64, "audio/amr"),
    "aac_adts": (b"\xff\xf1\x50\x80" + b"\x00" * 64, "audio/aac"),
    "wav": (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64, "audio/wav"),
    "ogg": (b"OggS\x00\x02" + b"\x00" * 64, "audio/ogg"),
}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Device-token requests fall in the 60/min per-IP tier, kept in the local Redis across test files; this file alone
    sends more than that, which would make the next file's requests 429."""
    from app.middleware import rate_limit
    monkeypatch.setattr(rate_limit, "_check_limit", lambda *a, **k: (True, 0))


@pytest.fixture()
def stored(monkeypatch):
    out = []
    monkeypatch.setattr(media_storage, "upload_call_recording", lambda key, data, ctype: out.append((key, len(data), ctype)))
    return out


@pytest.fixture()
def transcribed(monkeypatch):
    from app.workers.tasks import transcribe
    out = []
    monkeypatch.setattr(transcribe.transcribe, "delay", lambda **kw: out.append(kw))
    return out


def _known_guest(db, tid):
    guest_id, _ = identity_service.resolve_gid(db, tid, "phone", KNOWN, source="test")
    db.commit()
    return guest_id


def _upload_call(client, dev, cid="log-1", **kw):
    r = client.post("/api/v1/device-calls", json={"calls": [_call(cid=cid, **kw)]}, headers=_auth(dev["token"]))
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["status"]


def _post(client, token, cid="log-1", data=M4A, name="rec.m4a", ctype="audio/mp4"):
    return client.post(f"/api/v1/device-calls/{cid}/recording", files={"file": (name, data, ctype)}, headers=_auth(token))


def _app_call(db, dev, cid="log-1"):
    return db.query(Call).filter_by(ivr_call_id=f"mobile_app:{dev['id']}:{cid}").one()


@pytest.mark.parametrize("name", SAMPLES)
def test_magic_bytes_decide_the_type(name):
    data, ctype = SAMPLES[name]
    assert sniff_audio(data) == ctype


@pytest.mark.parametrize("data", [b"%PDF-1.7 hello", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, b"<html>audio</html>",
                                  b"PK\x03\x04" + b"\x00" * 32, b"\xff"])
def test_non_audio_is_not_sniffed(data):
    assert sniff_audio(data) is None


def test_recording_after_call_attaches_and_starts_transcription(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    tid = _tid(tenant_and_user)
    guest_id = _known_guest(db, tid)
    staff, staff_h = _user(db, tid)
    dev = _register(client, staff_h)
    assert _upload_call(client, dev) == "queued"
    _run_ingest(monkeypatch, db, queued)
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).count() == 0   # ingest consumed the waiting row
    r = _post(client, dev["token"])
    assert r.status_code == 201, r.text
    call = _app_call(db, dev)
    db.refresh(call)
    assert r.json() == {"status": "attached", "call_id": call.id} and call.guest_id == guest_id
    [(key, size, ctype)] = stored
    assert key.startswith(f"{tid}/calls/mobile_app/{dev['id']}/") and size == len(M4A) and ctype == "audio/mp4"
    assert call.recording_s3_key == key and call.recording_status == RecordingStatus.AVAILABLE
    assert call.transcription_status == "queued" and transcribed == [{"call_id": call.id, "tenant_id": tid}]
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).count() == 0
    audit = db.query(AuditEvent).filter_by(tenant_id=tid, action="call.recording_uploaded").one()
    assert audit.target_id == call.id and audit.actor_user_id == staff.id and KNOWN not in str(audit.payload)


def test_duplicate_upload_is_ignored(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    _known_guest(db, _tid(tenant_and_user))
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev)
    _run_ingest(monkeypatch, db, queued)
    assert _post(client, dev["token"]).status_code == 201
    again = _post(client, dev["token"], data=SAMPLES["mp3_id3"][0], name="other.mp3")
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    assert len(stored) == 1 and len(transcribed) == 1
    assert db.query(AuditEvent).filter_by(action="call.recording_uploaded").count() == 1


def test_recording_before_call_waits_and_is_linked_by_ingest(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    tid = _tid(tenant_and_user)
    _known_guest(db, tid)
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev)          # queued, ingest has not run yet
    r = _post(client, dev["token"])
    assert r.status_code == 202 and r.json() == {"status": "waiting", "call_id": None}
    row = db.query(MobileCallPending).filter_by(tenant_id=tid).one()
    assert row.recording_key == stored[0][0] and row.recording_type == "audio/mp4" and transcribed == []
    dup = _post(client, dev["token"])                      # a resend while waiting is still one recording
    assert dup.status_code == 200 and dup.json()["status"] == "duplicate" and len(stored) == 1

    _run_ingest(monkeypatch, db, queued)
    call = _app_call(db, dev)
    db.refresh(call)
    assert call.recording_s3_key == stored[0][0] and call.recording_status == RecordingStatus.AVAILABLE
    assert transcribed == [{"call_id": call.id, "tenant_id": tid}]
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).count() == 0
    # The task delivered again (Celery retry): no second link, no second transcription.
    payload = {"ivr_call_id": call.ivr_call_id, "direction": "inbound", "from_number": KNOWN, "to_number": "",
               "duration_sec": 42, "answered": True, "started_at": call.started_at, "ended_at": call.ended_at}
    queued.append((payload, tid, "mobile_app"))
    assert [x["status"] for x in _run_ingest(monkeypatch, db, queued)] == ["already_exists"]
    assert len(transcribed) == 1 and _post(client, dev["token"]).json()["status"] == "duplicate"


def test_short_call_recording_is_stored_but_not_transcribed(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    _known_guest(db, _tid(tenant_and_user))
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev, duration=4)
    _run_ingest(monkeypatch, db, queued)
    assert _post(client, dev["token"]).status_code == 201
    call = _app_call(db, dev)
    db.refresh(call)
    assert call.recording_s3_key and call.transcription_status == "skipped_short_call" and transcribed == []


@pytest.mark.parametrize("data, name, ctype, status", [
    (b"%PDF-1.7 not audio" + b"\x00" * 64, "rec.m4a", "audio/mp4", 415),   # the name and Content-Type lie
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "rec.mp3", "audio/mpeg", 415),
    (b"", "rec.m4a", "audio/mp4", 422),
])
def test_wrong_type_or_empty_is_refused(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed, data, name, ctype, status):
    _known_guest(db, _tid(tenant_and_user))
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev)
    _run_ingest(monkeypatch, db, queued)
    assert _post(client, dev["token"], data=data, name=name, ctype=ctype).status_code == status
    assert stored == [] and transcribed == []


def test_missing_file_field_is_refused(client, db, tenant_and_user, stored):
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    r = client.post("/api/v1/device-calls/log-1/recording", data={"note": "x"}, headers=_auth(dev["token"]))
    assert r.status_code == 422 and stored == []


def test_over_50_mb_is_refused(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    assert mobile_device_service.MAX_RECORDING_BYTES == 50 * 1024 * 1024
    _known_guest(db, _tid(tenant_and_user))
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev)
    _run_ingest(monkeypatch, db, queued)
    monkeypatch.setattr(mobile_device_service, "MAX_RECORDING_BYTES", 2048)   # same code path, without a 50 MB test body
    assert _post(client, dev["token"], data=M4A + b"\x00" * 3000).status_code == 413     # file over the cap
    assert _post(client, dev["token"], data=M4A + b"\x00" * 100_000).status_code == 413  # refused on Content-Length
    assert _post(client, dev["token"], data=M4A).status_code == 201                      # under the cap: fine
    assert len(stored) == 1


def test_other_device_and_other_tenant_get_404(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    tid = _tid(tenant_and_user)
    _known_guest(db, tid)
    owner_dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, owner_dev)                    # waiting row exists for owner_dev's call log-1
    _, staff_h = _user(db, tid)
    other_dev = _register(client, staff_h)
    other = _other_tenant(db)
    from app.models.user import UserRole
    _, foreign_h = _user(db, other.id, UserRole.OWNER)
    foreign_dev = _register(client, foreign_h)
    assert _post(client, other_dev["token"]).status_code == 404
    assert _post(client, foreign_dev["token"]).status_code == 404
    _run_ingest(monkeypatch, db, queued)
    assert _post(client, other_dev["token"]).status_code == 404     # still not theirs once the call exists
    assert _post(client, foreign_dev["token"]).status_code == 404
    assert stored == [] and _app_call(db, owner_dev).recording_s3_key is None


def test_call_the_server_refused_cannot_get_a_recording(client, db, tenant_and_user, queued, stored):
    """An unknown number skipped by the privacy rule leaves nothing to attach to: its audio is never stored."""
    dev = _register(client, _auth(tenant_and_user["access_token"]), settings={"unknown_numbers": "never"})
    assert _upload_call(client, dev, number=UNKNOWN) == "skipped_unknown_number"
    assert _post(client, dev["token"]).status_code == 404 and stored == []


def test_revoked_token_is_401(client, db, tenant_and_user, queued, stored):
    _known_guest(db, _tid(tenant_and_user))
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev)
    assert client.delete(f"/api/v1/devices/{dev['id']}", headers=_auth(tenant_and_user["access_token"])).status_code == 204
    assert _post(client, dev["token"]).status_code == 401
    assert _post(client, "haip_dev_nope").status_code == 401 and stored == []


def test_erasure_deletes_the_recording_and_any_waiting_row(client, db, tenant_and_user, queued, monkeypatch, stored, transcribed):
    from app.services import dpdp_erasure_service

    tid = _tid(tenant_and_user)
    guest_id = _known_guest(db, tid)
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev, cid="log-1")
    _upload_call(client, dev, cid="log-2")
    _run_ingest(monkeypatch, db, queued)
    assert _post(client, dev["token"], cid="log-1").status_code == 201
    attached = stored[0][0]
    # A recording for log-2 left waiting (e.g. its link failed): it belongs to the same person's call.
    waiting_key = f"{tid}/calls/mobile_app/{dev['id']}/stuck/recording"
    db.add(MobileCallPending(tenant_id=tid, device_pk=dev["id"], ivr_call_id=f"mobile_app:{dev['id']}:log-2",
                             recording_key=waiting_key, recording_type="audio/mp4", recording_bytes=10))
    db.commit()

    result = dpdp_erasure_service.erase_guest(db, tid, guest_id)
    db.commit()
    assert set(result["files"]) >= {attached, waiting_key}
    assert result["rows"].get("mobile_call_pending") == 1
    assert db.query(Call).filter_by(tenant_id=tid, guest_id=guest_id).count() == 0
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).count() == 0

    deleted = []

    class _S3:
        def delete_objects(self, Bucket, Delete):
            deleted.extend(o["Key"] for o in Delete["Objects"])

    monkeypatch.setattr(media_storage, "_s3_client", lambda: _S3())
    media_storage.delete_tenant_objects(tid, result["files"])   # the erasure job's own file step
    assert {attached, waiting_key} <= set(deleted)


def test_stale_waiting_rows_are_swept_with_their_file(client, db, tenant_and_user, queued, monkeypatch):
    from sqlalchemy.orm import Session as SASession
    from app.workers.tasks import mobile_calls

    tid = _tid(tenant_and_user)
    _known_guest(db, tid)
    dev = _register(client, _auth(tenant_and_user["access_token"]))
    _upload_call(client, dev, cid="old")
    _upload_call(client, dev, cid="new")
    old = db.query(MobileCallPending).filter_by(ivr_call_id=f"mobile_app:{dev['id']}:old").one()
    old_key = old.recording_key = f"{tid}/calls/mobile_app/{dev['id']}/old/recording"
    old.created_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()
    deleted = []
    monkeypatch.setattr(mobile_calls, "SessionLocal", lambda: SASession(bind=db.connection()))
    monkeypatch.setattr(media_storage, "delete_tenant_objects", lambda t, keys: deleted.append((t, keys)) or len(keys))
    assert mobile_calls.purge_stale_pending.run() == {"files": 1}
    assert deleted == [(tid, [old_key])]
    db.expire_all()
    assert [r.ivr_call_id for r in db.query(MobileCallPending).filter_by(tenant_id=tid)] == [f"mobile_app:{dev['id']}:new"]
