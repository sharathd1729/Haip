"""One recording download, one transcription per call (AI_COST_SPEC step 0 trace: the same call was transcribed and
analysed again because several IVR webhooks each queued a fetch, a fetch that failed early retried an hour later and
stored the recording again, and queue_transcription set a "done" call back to "queued").
Real database rows, so the guarded UPDATEs are exercised; the IVR adapter, S3 and Celery are faked."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session as SASession

from app.models.call import Call, RecordingStatus
from app.workers.tasks import call_ingest, transcribe
from tests.test_calls_app_reliability import _stuck_call
from tests.workers import call_analysis_harness as h


def _fetch(db, call):
    """Run the fetch body; the adapter records the download and fails (so no S3 write), like a not-yet-ready recording."""
    downloads = []

    async def _download(url):
        downloads.append(url)
        raise RuntimeError("recording not ready")

    adapter = MagicMock()
    adapter.fetch_recording = _download
    task_self = MagicMock()
    task_self.request.retries = 0
    task_self.retry.side_effect = lambda exc, countdown=None: exc
    with (
        patch.object(call_ingest, "SessionLocal", lambda: SASession(bind=db.connection())),
        patch.object(call_ingest, "get_ivr_adapter", return_value=adapter),
    ):
        try:
            call_ingest._do_fetch_recording(task_self, call.id, "https://rec.example/x.mp3", call.tenant_id, "acefone")
        except RuntimeError:
            pass
    return downloads


def _set(db, call, **fields):
    for k, v in fields.items():
        setattr(call, k, v)
    db.commit()
    return call


def test_a_recording_already_stored_is_not_downloaded_again(db):
    call = _stuck_call(db, h.tenant(db).id, status="done")  # recording AVAILABLE with an S3 key
    assert _fetch(db, call) == []


def test_a_recording_another_copy_is_downloading_is_left_alone(db):
    call = _stuck_call(db, h.tenant(db).id, status="pending")
    _set(db, call, recording_s3_key=None, recording_status=RecordingStatus.FETCHING, updated_at=datetime.now(UTC))
    assert _fetch(db, call) == []


@pytest.mark.parametrize(
    "state",
    [
        {"recording_status": RecordingStatus.PENDING},
        {"recording_status": RecordingStatus.MISSING_RETRY_1},  # the hourly retry
        {
            "recording_status": RecordingStatus.FETCHING,
            "updated_at": datetime.now(UTC) - timedelta(hours=1),
        },  # worker died
    ],
)
def test_a_recording_not_yet_stored_is_downloaded(db, state):
    call = _stuck_call(db, h.tenant(db).id, status="pending")
    _set(db, call, recording_s3_key=None, **state)
    assert _fetch(db, call) == ["https://rec.example/x.mp3"]


def test_queue_transcription_never_resets_a_finished_transcription(db):
    call = _stuck_call(db, h.tenant(db).id, status="done")
    with patch("app.workers.tasks.transcribe.transcribe.delay") as queued:
        call_ingest.queue_transcription(db, call)
    queued.assert_not_called()
    assert db.get(Call, call.id).transcription_status == "done"


def test_queue_transcription_still_queues_a_new_recording(db):
    call = _stuck_call(db, h.tenant(db).id, status="pending")
    with patch("app.workers.tasks.transcribe.transcribe.delay") as queued:
        call_ingest.queue_transcription(db, call)
    queued.assert_called_once()
    assert db.get(Call, call.id).transcription_status == "queued"


def _transcribe(db, call):
    started = []
    with (
        patch.object(transcribe, "SessionLocal", lambda: SASession(bind=db.connection())),
        patch.object(
            transcribe, "get_transcription_adapter", side_effect=lambda *a, **k: started.append(1) or MagicMock()
        ),
    ):
        try:
            transcribe.transcribe.run(call_id=call.id, tenant_id=call.tenant_id)
        except Exception:  # noqa: BLE001 -- past the claim the fake recording cannot be read; only the claim matters here
            pass
    return started


def test_a_transcription_another_copy_is_running_is_skipped(db):
    call = _stuck_call(db, h.tenant(db).id, status="processing")
    _set(db, call, updated_at=datetime.now(UTC))
    assert _transcribe(db, call) == []


def test_an_abandoned_transcription_is_taken_over(db, tmp_path):
    call = _stuck_call(db, h.tenant(db).id, status="processing")
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"ID3")
    _set(db, call, recording_s3_key=str(audio), updated_at=datetime.now(UTC) - timedelta(hours=2))
    assert _transcribe(db, call) == [1]
