"""
Tests for the Sarvam batch Speech-to-Text adapter (adapters/transcription/sarvam.py).

Covers:
  - _parse()'s handling of diarized vs. plain-timestamp responses
  - Regression for the live KeyError(0) bug: timestamps coming back as a
    dict instead of a list must not crash, matching the real-time
    endpoint's response shape (same _parse/_turns_from_* code is reused
    for batch output).
  - transcribe()'s full batch job flow (create -> upload -> start -> wait
    -> download -> parse), with the sarvamai SDK mocked out entirely --
    no real network/API key needed.
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.transcription.sarvam import SarvamAdapter


def _adapter():
    return SarvamAdapter(api_key="test-key")


# ── _parse() ─────────────────────────────────────────────────────────────────

def test_parse_prefers_diarized_entries():
    payload = {
        "transcript": "hello there general kenobi",
        "language_code": "hi-IN",
        "diarized_transcript": {
            "entries": [
                {"speaker": "SPEAKER_00", "transcript": "hello there", "start": 0.0, "end": 1.2},
                {"speaker": "SPEAKER_01", "transcript": "general kenobi", "start": 1.2, "end": 2.5},
            ]
        },
    }
    result = _adapter()._parse(payload, "hi-IN")
    assert len(result.turns) == 2
    assert result.turns[0].speaker == "agent"
    assert result.turns[1].speaker == "guest"
    assert result.provider == "sarvam"


def test_parse_falls_back_to_timestamps_when_no_diarization():
    payload = {
        "transcript": "hello world",
        "language_code": "en-IN",
        "timestamps": [
            {"word": "hello", "start": 0.0, "end": 0.4},
            {"word": "world", "start": 0.4, "end": 0.8},
        ],
    }
    result = _adapter()._parse(payload, "en-IN")
    assert len(result.turns) == 1
    assert "hello" in result.turns[0].text


def test_parse_handles_missing_timestamps_entirely():
    payload = {"transcript": "just text", "language_code": "hi-IN"}
    result = _adapter()._parse(payload, "hi-IN")
    assert result.turns[0].text == "just text"


def test_parse_does_not_crash_when_timestamps_is_a_dict_not_a_list():
    """Regression: seen live as KeyError(0) on timestamps[0] when the
    'timestamps' field came back as a dict rather than a list."""
    payload = {
        "transcript": "some text",
        "language_code": "hi-IN",
        "timestamps": {"unexpected": "shape"},
    }
    result = _adapter()._parse(payload, "hi-IN")
    assert result.turns[0].text == "some text"


# ── transcribe() batch job flow ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_transcribe_runs_full_batch_job_flow(tmp_path):
    fake_payload = {
        "transcript": "namaste, kaise ho",
        "language_code": "hi-IN",
        "diarized_transcript": {"entries": [
            {"speaker": "SPEAKER_00", "transcript": "namaste, kaise ho", "start": 0.0, "end": 3.0},
        ]},
    }

    output_dir_holder = {}

    def fake_download_outputs(output_dir):
        output_dir_holder["dir"] = output_dir
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "recording.wav.json"), "w") as f:
            json.dump(fake_payload, f)
        return True

    fake_job = MagicMock()
    fake_job.is_successful.return_value = True
    fake_job.download_outputs.side_effect = fake_download_outputs

    fake_client = MagicMock()
    fake_client.speech_to_text_job.create_job.return_value = fake_job

    with patch("app.adapters.transcription.sarvam.SarvamAI", return_value=fake_client):
        result = await _adapter().transcribe(b"fake-wav-bytes", language_hint="hi-IN")

    fake_client.speech_to_text_job.create_job.assert_called_once()
    call_kwargs = fake_client.speech_to_text_job.create_job.call_args.kwargs
    assert call_kwargs["model"] == "saarika:v2.5"
    assert call_kwargs["with_timestamps"] is True
    assert call_kwargs["with_diarization"] is True

    fake_job.upload_files.assert_called_once()
    fake_job.start.assert_called_once()
    fake_job.wait_until_complete.assert_called_once()

    assert result.raw_text == "namaste, kaise ho"
    assert result.turns[0].speaker == "agent"
    assert result.provider == "sarvam"


@pytest.mark.asyncio
async def test_transcribe_raises_on_failed_job():
    fake_job = MagicMock()
    fake_job.is_successful.return_value = False
    fake_job.job_id = "job-123"
    fake_job.get_file_results.return_value = {
        "failed": [{"file_name": "recording.wav", "error_message": "corrupt audio"}],
        "successful": [],
    }

    fake_client = MagicMock()
    fake_client.speech_to_text_job.create_job.return_value = fake_job

    with patch("app.adapters.transcription.sarvam.SarvamAI", return_value=fake_client):
        with pytest.raises(RuntimeError, match="corrupt audio"):
            await _adapter().transcribe(b"fake-wav-bytes", language_hint="hi-IN")
