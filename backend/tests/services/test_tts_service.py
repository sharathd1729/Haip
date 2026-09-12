"""IVR TTS output must be telephony-native.

Ratha's live greeting.mp3 measured 22050 Hz (Sarvam's default -- the
parameter was simply never passed). Telephony carries 8 kHz, and 22050
resamples into it at a non-integer 2.756 ratio, mid-call, in the <Play>
immediately before <Dial> builds the bridge. Inbound calls showed both
legs recorded clearly while neither party could hear the other; outbound
click-to-call, the one path that plays nothing before dialing, was always
fine. These pin the rate so it can't silently drift back.
"""
import base64
from types import SimpleNamespace

import pytest

from app.services import tts_service


class _FakeTTS:
    def __init__(self, sink):
        self._sink = sink

    def convert(self, **kwargs):
        self._sink.update(kwargs)
        return SimpleNamespace(
            audios=[base64.b64encode(b"fake-mp3").decode()],
            request_id="req-1",
        )


class _FakeClient:
    def __init__(self, sink):
        self.text_to_speech = _FakeTTS(sink)


@pytest.fixture()
def sent(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(tts_service, "SarvamAI", lambda **kw: _FakeClient(captured))
    return captured


def test_tts_requests_8khz_telephony_audio(sent):
    tts_service.generate_speech("Namaskara and welcome to Ratha Retreats.")
    assert sent["speech_sample_rate"] == 8000


def test_tts_default_constant_is_telephony_rate():
    """8000 Hz is the only rate that needs no resampling on a PSTN leg."""
    assert tts_service.SPEECH_SAMPLE_RATE_HZ == 8000


def test_tts_sample_rate_is_overridable(sent):
    tts_service.generate_speech("hi", speech_sample_rate=16000)
    assert sent["speech_sample_rate"] == 16000


def test_tts_still_requests_mp3_and_returns_decoded_bytes(sent):
    out = tts_service.generate_speech("hi", speaker="manisha")
    assert sent["output_audio_codec"] == "mp3"
    assert sent["speaker"] == "manisha"
    assert sent["model"] == "bulbul:v2"
    assert out == b"fake-mp3"


def test_tts_raises_when_no_audio_comes_back(monkeypatch):
    class _Empty:
        def convert(self, **kwargs):
            return SimpleNamespace(audios=[], request_id="req-2")

    monkeypatch.setattr(
        tts_service, "SarvamAI",
        lambda **kw: SimpleNamespace(text_to_speech=_Empty()),
    )
    with pytest.raises(RuntimeError):
        tts_service.generate_speech("hi")
