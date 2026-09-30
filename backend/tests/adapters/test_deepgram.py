"""
Tests for the Deepgram transcription adapter (adapters/transcription/deepgram.py).

Covers the diarization-collapse regression: when Deepgram's diarization
tags every utterance with the same speaker id (crossed/noisy audio, very
short calls), the old "speaker 0 == agent" heuristic mislabeled the whole
transcript as "agent" since that's trivially true with only one id present.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.transcription.deepgram import DeepgramAdapter


def _mock_response(utterances: list[dict]):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "results": {
            "channels": [{"detected_language": "en"}],
            "utterances": utterances,
        }
    })
    return resp


@pytest.mark.asyncio
async def test_transcribe_labels_agent_guest_when_diarization_finds_two_speakers():
    utterances = [
        {"speaker": 0, "transcript": "hello there", "start": 0.0, "end": 1.2},
        {"speaker": 1, "transcript": "general kenobi", "start": 1.2, "end": 2.5},
    ]
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=_mock_response(utterances))
        result = await DeepgramAdapter().transcribe(b"fake-audio")

    assert len(result.turns) == 2
    assert result.turns[0].speaker == "agent"
    assert result.turns[1].speaker == "guest"


@pytest.mark.asyncio
async def test_transcribe_flips_roles_on_outbound_calls():
    """Real bug (Ratha, Sep 2026): the callee (guest) answers and speaks
    first on an outbound call, reversing "speaker 0 == agent"."""
    utterances = [
        {"speaker": 0, "transcript": "hello is this ratha caravans", "start": 0.0, "end": 2.0},
        {"speaker": 1, "transcript": "yes how can i help", "start": 2.0, "end": 3.5},
    ]
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=_mock_response(utterances))
        result = await DeepgramAdapter().transcribe(b"fake-audio", direction="outbound")

    assert result.turns[0].speaker == "guest"
    assert result.turns[1].speaker == "agent"


@pytest.mark.asyncio
async def test_transcribe_labels_unknown_when_diarization_collapses_to_one_speaker():
    """Confirmed live: a call clearly alternating between two people came
    back with every utterance tagged speaker=0 -- diarization ran but
    failed to distinguish anyone. Must fall back to "unknown" rather than
    the old "speaker 0 == agent" heuristic which is trivially true here."""
    utterances = [
        {"speaker": 0, "transcript": "hello there", "start": 0.0, "end": 1.2},
        {"speaker": 0, "transcript": "general kenobi", "start": 1.2, "end": 2.5},
        {"speaker": 0, "transcript": "how are you", "start": 2.5, "end": 3.5},
    ]
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=_mock_response(utterances))
        result = await DeepgramAdapter().transcribe(b"fake-audio")

    assert len(result.turns) == 3
    assert all(t.speaker == "unknown" for t in result.turns)
