"""
Tests for B15: Recording fetch — handle missing S3 object gracefully.

Covers:
- RecordingStatus enum values exist and are strings
- fetch_and_store_recording: success → AVAILABLE
- fetch_and_store_recording: first failure → MISSING_RETRY_1, retry in +1h
- fetch_and_store_recording: second failure → MISSING_RETRY_2, retry in +6h
- fetch_and_store_recording: third failure → MISSING_RETRY_3, retry in +24h
- fetch_and_store_recording: fourth failure → PERMANENTLY_MISSING (no retry)
- transcribe_call: S3 NoSuchKey → marks PERMANENTLY_MISSING, does not raise
- transcribe_call: S3 AccessDenied → re-raises (retryable)
- _RETRY_DELAYS has exactly 3 entries matching 1h/6h/24h
"""

import pytest
from unittest.mock import patch, MagicMock, call as mock_call
from botocore.exceptions import ClientError

from app.models.call import RecordingStatus, Call
from app.workers.tasks.call_ingest import (
    fetch_and_store_recording,
    _do_fetch_recording,
    _RETRY_DELAYS,
    _RETRY_STATES,
)


# ─────────────────────────────────────────────────────────────────
# Enum smoke tests
# ─────────────────────────────────────────────────────────────────

def test_recording_status_values():
    assert RecordingStatus.PENDING.value == "pending"
    assert RecordingStatus.FETCHING.value == "fetching"
    assert RecordingStatus.AVAILABLE.value == "available"
    assert RecordingStatus.MISSING_RETRY_1.value == "missing_retry_1"
    assert RecordingStatus.MISSING_RETRY_2.value == "missing_retry_2"
    assert RecordingStatus.MISSING_RETRY_3.value == "missing_retry_3"
    assert RecordingStatus.PERMANENTLY_MISSING.value == "permanently_missing"


def test_retry_schedule_has_three_entries():
    assert len(_RETRY_DELAYS) == 3
    assert _RETRY_DELAYS == [3600, 21600, 86400], "Expected 1h / 6h / 24h"


def test_retry_states_aligned_with_delays():
    assert len(_RETRY_STATES) == len(_RETRY_DELAYS)
    assert _RETRY_STATES[0] == RecordingStatus.MISSING_RETRY_1
    assert _RETRY_STATES[1] == RecordingStatus.MISSING_RETRY_2
    assert _RETRY_STATES[2] == RecordingStatus.MISSING_RETRY_3


# ─────────────────────────────────────────────────────────────────
# fetch_and_store_recording unit tests
# ─────────────────────────────────────────────────────────────────

def _make_call(call_id="c1", tenant_id="t1"):
    c = MagicMock(spec=Call)
    c.id = call_id
    c.tenant_id = tenant_id
    c.recording_url_ivr = "https://ivr.example.com/rec.mp3"
    c.recording_status = RecordingStatus.PENDING
    c.recording_error = None
    c.duration_seconds = 30  # "normal" call by default; short-call tests override this
    return c


def _mock_db(call=None):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = call
    return db


def _run_fetch(call, retries=0, s3_side_effect=None, audio_bytes=b"audio"):
    """
    Drive _do_fetch_recording (extracted task body) with a plain mock task_self.
    No Celery machinery involved — tests the logic directly.
    """
    db = _mock_db(call)

    mock_adapter = MagicMock()

    async def _fake_fetch(url):
        if s3_side_effect:
            raise s3_side_effect
        return audio_bytes

    mock_adapter.fetch_recording = _fake_fetch
    mock_s3 = MagicMock()

    # Plain mock — no Celery property descriptors
    task_self = MagicMock()
    task_self.request.retries = retries
    task_self.max_retries = len(_RETRY_DELAYS)

    def _do_retry(exc, countdown=None):
        raise exc  # surface so the test can assert on it

    task_self.retry.side_effect = _do_retry

    with patch("app.workers.tasks.call_ingest.SessionLocal", return_value=db), \
         patch("app.workers.tasks.call_ingest.get_ivr_adapter", return_value=mock_adapter), \
         patch("app.workers.tasks.call_ingest.boto3.client", return_value=mock_s3), \
         patch("app.workers.tasks.transcribe.transcribe"):

        _do_fetch_recording(
            task_self,
            call_id=call.id,
            recording_url=call.recording_url_ivr,
            tenant_id=call.tenant_id,
            ivr_provider="callerdesk",
        )

    return call, db, mock_s3


class TestFetchAndStoreRecording:
    def test_success_sets_available(self):
        call = _make_call()
        _run_fetch(call)
        assert call.recording_status == RecordingStatus.AVAILABLE
        assert call.recording_error is None
        assert call.recording_fetched is True

    def test_first_failure_sets_missing_retry_1(self):
        call = _make_call()
        with pytest.raises(Exception):
            _run_fetch(call, retries=0, s3_side_effect=RuntimeError("IVR not ready"))
        assert call.recording_status == RecordingStatus.MISSING_RETRY_1

    def test_second_failure_sets_missing_retry_2(self):
        call = _make_call()
        with pytest.raises(Exception):
            _run_fetch(call, retries=1, s3_side_effect=RuntimeError("still not ready"))
        assert call.recording_status == RecordingStatus.MISSING_RETRY_2

    def test_third_failure_sets_missing_retry_3(self):
        call = _make_call()
        with pytest.raises(Exception):
            _run_fetch(call, retries=2, s3_side_effect=RuntimeError("still missing"))
        assert call.recording_status == RecordingStatus.MISSING_RETRY_3

    def test_fourth_failure_sets_permanently_missing_no_retry(self):
        """retries == max_retries → permanently_missing, no further retry."""
        call = _make_call()
        # Should NOT raise — on exhaustion we give up gracefully
        _run_fetch(call, retries=3, s3_side_effect=RuntimeError("gone forever"))
        assert call.recording_status == RecordingStatus.PERMANENTLY_MISSING

    def test_error_text_stored_on_failure(self):
        call = _make_call()
        with pytest.raises(Exception):
            _run_fetch(call, retries=0, s3_side_effect=RuntimeError("specific error"))
        assert "specific error" in (call.recording_error or "")

    def test_short_call_skips_transcription_and_scoring(self):
        """Calls under 10s never carry a real conversation -- shouldn't
        burn a transcription/scoring API call, and previously sat at
        transcription_status='queued' forever since nothing dequeued them."""
        call = _make_call()
        call.duration_seconds = 3
        _run_fetch(call)
        assert call.transcription_status == "skipped_short_call"
        assert call.ai_score_status == "skipped_short_call"
        # Recording itself still gets stored -- only AI processing is skipped.
        assert call.recording_status == RecordingStatus.AVAILABLE

    def test_call_at_exactly_threshold_is_not_skipped(self):
        call = _make_call()
        call.duration_seconds = 10
        _run_fetch(call)
        assert call.transcription_status != "skipped_short_call"
        assert call.transcription_status == "queued"

    def test_call_with_zero_duration_is_skipped(self):
        call = _make_call()
        call.duration_seconds = 0
        _run_fetch(call)
        assert call.transcription_status == "skipped_short_call"
        assert call.ai_score_status == "skipped_short_call"

    def test_long_call_still_queues_transcription(self):
        call = _make_call()
        call.duration_seconds = 45
        _run_fetch(call)
        assert call.transcription_status == "queued"

    def test_call_not_found_returns_early(self):
        db = _mock_db(call=None)
        task_self = MagicMock()
        task_self.request.retries = 0
        with patch("app.workers.tasks.call_ingest.SessionLocal", return_value=db), \
             patch("app.workers.tasks.call_ingest.get_ivr_adapter"):
            _do_fetch_recording(
                task_self,
                call_id="nonexistent",
                recording_url="https://example.com/r.mp3",
                tenant_id="t1",
                ivr_provider="callerdesk",
            )
        task_self.retry.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# transcribe_call S3 error handling
# ─────────────────────────────────────────────────────────────────

def _make_s3_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "test"}},
        "GetObject",
    )


class TestTranscribeCallS3Errors:
    def _run(self, call, s3_error=None):
        from app.workers.tasks.transcription import _do_transcribe

        db = _mock_db(call)
        mock_s3 = MagicMock()
        if s3_error:
            mock_s3.get_object.side_effect = s3_error

        task_self = MagicMock()
        task_self.request.retries = 0

        def _do_retry(exc, **kw):
            raise exc

        task_self.retry.side_effect = _do_retry

        with patch("app.workers.tasks.transcription.SessionLocal", return_value=db), \
             patch("app.workers.tasks.transcription.boto3.client", return_value=mock_s3):
            _do_transcribe(task_self, call_id=call.id, tenant_id=call.tenant_id)

        return call

    def test_no_s3_key_returns_early(self):
        call = _make_call()
        call.recording_s3_key = None
        self._run(call)  # should not raise

    def test_no_such_key_marks_permanently_missing(self):
        call = _make_call()
        call.recording_s3_key = "tenant/calls/c1/recording.mp3"

        result = self._run(call, s3_error=_make_s3_error("NoSuchKey"))
        assert result.recording_status == RecordingStatus.PERMANENTLY_MISSING
        assert result.transcription_status == "failed"

    def test_404_marks_permanently_missing(self):
        call = _make_call()
        call.recording_s3_key = "tenant/calls/c1/recording.mp3"

        result = self._run(call, s3_error=_make_s3_error("404"))
        assert result.recording_status == RecordingStatus.PERMANENTLY_MISSING

    def test_access_denied_reraises(self):
        """AccessDenied is a misconfiguration, not a missing file — should be retried."""
        from app.workers.tasks.transcription import _do_transcribe

        call = _make_call()
        call.recording_s3_key = "tenant/calls/c1/recording.mp3"

        db = _mock_db(call)
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = _make_s3_error("AccessDenied")

        retry_called = []
        task_self = MagicMock()
        task_self.request.retries = 0

        def _do_retry(exc, **kw):
            retry_called.append(exc)
            raise exc

        task_self.retry.side_effect = _do_retry

        with patch("app.workers.tasks.transcription.SessionLocal", return_value=db), \
             patch("app.workers.tasks.transcription.boto3.client", return_value=mock_s3):
            with pytest.raises(ClientError):
                _do_transcribe(task_self, call_id=call.id, tenant_id=call.tenant_id)

        assert retry_called, "retry() should have been triggered for AccessDenied"
