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

from app.adapters.transcription.sarvam import SarvamAdapter, _sniff_audio_extension


def _adapter():
    return SarvamAdapter(api_key="test-key")


# ── _sniff_audio_extension() ────────────────────────────────────────────────

def test_sniff_audio_extension_detects_wav_by_riff_header():
    assert _sniff_audio_extension(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"


def test_sniff_audio_extension_defaults_to_mp3():
    """Confirmed live: transcribe.py fetches the recording straight from S3
    with zero format conversion, and Vobiz (the only confirmed live
    provider) stores recordings as .mp3 -- this adapter previously wrote
    those exact MP3 bytes into a file unconditionally named "recording.wav",
    regardless of actual content."""
    mp3_bytes = b"\xff\xfb\x90\x00" + b"\x00" * 20
    assert _sniff_audio_extension(mp3_bytes) == "mp3"


def test_sniff_audio_extension_defaults_to_mp3_for_unrecognized_bytes():
    assert _sniff_audio_extension(b"not a real audio file") == "mp3"


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


def test_parse_labels_unknown_when_diarization_collapses_to_one_speaker():
    """Confirmed live: a call clearly alternating between two people came
    back with every entry tagged the same raw speaker id -- diarization
    ran but failed to distinguish anyone. The old "first speaker == agent"
    heuristic mislabeled the entire transcript as "agent". Must fall back
    to "unknown" instead of a confident-but-wrong label."""
    payload = {
        "transcript": "hello there general kenobi how are you",
        "language_code": "hi-IN",
        "diarized_transcript": {
            "entries": [
                {"speaker": "SPEAKER_00", "transcript": "hello there", "start": 0.0, "end": 1.2},
                {"speaker": "SPEAKER_00", "transcript": "general kenobi", "start": 1.2, "end": 2.5},
                {"speaker": "SPEAKER_00", "transcript": "how are you", "start": 2.5, "end": 3.5},
            ]
        },
    }
    result = _adapter()._parse(payload, "hi-IN")
    assert len(result.turns) == 3
    assert all(t.speaker == "unknown" for t in result.turns)


def test_parse_handles_saaras_v3_field_names():
    """Confirmed live: saaras:v3 (the current model -- v2.5 is Sarvam's own
    explicitly-named legacy model) renamed diarized entry fields from
    "speaker"/"start"/"end" to "speaker_id"/"start_time_seconds"/
    "end_time_seconds". Real bug this was masking: the old field names
    silently returned None for every v3 entry, so diarization looked
    broken even on a real 30-minute call with two clearly alternating
    speakers -- it was actually just reading the wrong keys."""
    payload = {
        "transcript": "hello there general kenobi",
        "language_code": "en-IN",
        "diarized_transcript": {
            "entries": [
                {"speaker_id": "speaker_1", "transcript": "hello there", "start_time_seconds": 1.1, "end_time_seconds": 9.07},
                {"speaker_id": "speaker_2", "transcript": "general kenobi", "start_time_seconds": 9.5, "end_time_seconds": 12.0},
            ]
        },
    }
    result = _adapter()._parse(payload, "en-IN")
    assert len(result.turns) == 2
    assert result.turns[0].speaker == "agent"
    assert result.turns[0].t0 == 1.1
    assert result.turns[0].t1 == 9.07
    assert result.turns[1].speaker == "guest"
    assert result.turns[1].t0 == 9.5


def test_parse_v3_field_names_also_detect_a_collapsed_single_speaker():
    payload = {
        "transcript": "hello there general kenobi",
        "language_code": "en-IN",
        "diarized_transcript": {
            "entries": [
                {"speaker_id": "speaker_1", "transcript": "hello there", "start_time_seconds": 0.0, "end_time_seconds": 1.2},
                {"speaker_id": "speaker_1", "transcript": "general kenobi", "start_time_seconds": 1.2, "end_time_seconds": 2.5},
            ]
        },
    }
    result = _adapter()._parse(payload, "en-IN")
    assert all(t.speaker == "unknown" for t in result.turns)


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
    fake_client.speech_to_text_translate_job.create_job.return_value = fake_job

    with patch("app.adapters.transcription.sarvam.SarvamAI", return_value=fake_client):
        result = await _adapter().transcribe(b"fake-wav-bytes", language_hint="hi-IN")

    fake_client.speech_to_text_translate_job.create_job.assert_called_once()
    call_kwargs = fake_client.speech_to_text_translate_job.create_job.call_args.kwargs
    assert call_kwargs["model"] == "saaras:v3"
    assert call_kwargs["with_diarization"] is True
    assert call_kwargs["num_speakers"] == 2

    fake_job.upload_files.assert_called_once()
    fake_job.start.assert_called_once()
    fake_job.wait_until_complete.assert_called_once()

    assert result.raw_text == "namaste, kaise ho"
    # Single entry/single speaker -- can't honestly distinguish agent vs
    # guest from this alone, so "unknown" is correct (see the dedicated
    # diarization-collapse regression test above for that specific case).
    assert result.turns[0].speaker == "unknown"
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
    fake_client.speech_to_text_translate_job.create_job.return_value = fake_job

    with patch("app.adapters.transcription.sarvam.SarvamAI", return_value=fake_client):
        with pytest.raises(RuntimeError, match="corrupt audio"):
            await _adapter().transcribe(b"fake-wav-bytes", language_hint="hi-IN")
