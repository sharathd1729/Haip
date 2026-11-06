"""Mcube posts twice per call ("On Call", then "On Hangup" with length + recording). The second post used to be
dropped as a duplicate, leaving every call at 0 s and skipped for AI. It now fills the call in."""
import uuid

from sqlalchemy.orm import Session as SASession

from app.adapters.ivr.base import CallWebhookPayload
from app.models.call import Call, RecordingStatus
from app.workers.tasks import call_ingest
from app.workers.tasks.call_ingest import ingest_call


def _payload(call_id, secs, url=""):
    return CallWebhookPayload(
        ivr_call_id=call_id, direction="inbound", from_number="+917249066854", to_number="+918970663366",
        duration_seconds=secs, recording_url=url, agent_number="+919000000000",
        started_at="2026-11-06 10:00:00", ended_at="2026-11-06 10:02:05" if secs else "", provider="mcube", raw={},
    )


def _ingest(monkeypatch, db, tenant_id, payload, fetched, transcribed):
    monkeypatch.setattr(call_ingest, "get_ivr_adapter", lambda provider: type("A", (), {"parse_call_webhook": lambda s, r: payload})())
    monkeypatch.setattr(call_ingest.fetch_and_store_recording, "delay", lambda **kw: fetched.append(kw))
    from app.workers.tasks import transcribe
    monkeypatch.setattr(transcribe.transcribe, "delay", lambda **kw: transcribed.append(kw))
    monkeypatch.setattr(call_ingest, "SessionLocal", lambda: SASession(bind=db.connection()))
    return ingest_call.run(payload={}, tenant_id=tenant_id, ivr_provider="mcube")


def test_hangup_event_fills_length_and_fetches_the_recording(db, tenant_and_user, monkeypatch):
    tid, cid, fetched, transcribed = tenant_and_user["tenant"].id, f"mc-{uuid.uuid4().hex[:8]}", [], []
    first = _ingest(monkeypatch, db, tid, _payload(cid, 0), fetched, transcribed)
    assert first["status"] == "created"

    second = _ingest(monkeypatch, db, tid, _payload(cid, 125, "https://recordings.mcube.com/x.wav"), fetched, transcribed)
    assert second["status"] == "updated"
    call = db.query(Call).filter_by(id=first["call_id"]).one()
    assert call.duration_seconds == 125 and call.recording_url_ivr.endswith("x.wav")
    assert fetched[-1]["recording_url"].endswith("x.wav")       # fetch re-queued; it transcribes once stored


def test_already_stored_short_call_is_sent_to_transcription_when_length_arrives(db, tenant_and_user, monkeypatch):
    tid, cid, fetched, transcribed = tenant_and_user["tenant"].id, f"mc-{uuid.uuid4().hex[:8]}", [], []
    url = "https://recordings.mcube.com/y.wav"
    first = _ingest(monkeypatch, db, tid, _payload(cid, 0, url), fetched, transcribed)
    call = db.query(Call).filter_by(id=first["call_id"]).one()
    call.recording_status, call.recording_s3_key, call.transcription_status = RecordingStatus.AVAILABLE, "k/y.wav", "skipped_short_call"
    db.flush()

    assert _ingest(monkeypatch, db, tid, _payload(cid, 90, url), fetched, transcribed)["status"] == "updated"
    assert transcribed and transcribed[-1]["call_id"] == call.id
    db.expire_all()
    assert db.query(Call).filter_by(id=call.id).one().transcription_status == "queued"


def test_identical_repeat_is_still_a_no_op(db, tenant_and_user, monkeypatch):
    tid, cid, fetched, transcribed = tenant_and_user["tenant"].id, f"mc-{uuid.uuid4().hex[:8]}", [], []
    _ingest(monkeypatch, db, tid, _payload(cid, 60, "https://recordings.mcube.com/z.wav"), fetched, transcribed)
    again = _ingest(monkeypatch, db, tid, _payload(cid, 60, "https://recordings.mcube.com/z.wav"), fetched, transcribed)
    assert again["status"] == "already_exists"
