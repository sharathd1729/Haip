"""
Sarvam AI text-to-speech -- IVR greeting generation.

HAIP already uses Sarvam for speech-to-text (adapters/transcription/
sarvam.py); this is the first text-to-speech call site. One vendor, one
call site -- a plain service function, not a new adapters/tts/ package
(adapters/ is reserved for pluggable multi-provider abstractions like
transcription/LLM/IVR, which TTS isn't, yet).
"""
from __future__ import annotations
import base64
import structlog
from sarvamai import SarvamAI
from app.core.config import settings

log = structlog.get_logger()


# Telephony carries 8 kHz audio. Sarvam's default (22050 Hz -- measured on
# Ratha's live greeting.mp3, their docs say 24000) is neither a telephony
# rate nor an integer multiple of one: 22050/8000 = 2.756, the most awkward
# resample a media server can be handed, and it happens mid-call in the
# <Play> immediately before <Dial> sets up the bridge.
#
# This matters because the inbound IVR flow is the ONLY path that plays a
# file before bridging (outbound click-to-call dials straight out and has
# never had an audio complaint), and inbound calls were showing both legs
# recorded clearly while neither party could hear the other -- the
# signature of a codec/rate mismatch on the bridge rather than a dead leg.
SPEECH_SAMPLE_RATE_HZ = 8000


def generate_speech(
    text: str,
    speaker: str = "anushka",
    target_language_code: str = "en-IN",
    speech_sample_rate: int = SPEECH_SAMPLE_RATE_HZ,
) -> bytes:
    """
    Synthesize `text` via Sarvam's bulbul:v2 TTS model, returning MP3 bytes
    at a telephony-native sample rate (see SPEECH_SAMPLE_RATE_HZ).
    Raises RuntimeError on an empty/failed response -- no silent fallback.
    """
    client = SarvamAI(api_subscription_key=settings.SARVAM_API_KEY)

    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code=target_language_code,
            speaker=speaker,
            model="bulbul:v2",
            output_audio_codec="mp3",
            speech_sample_rate=speech_sample_rate,
        )
    except Exception as exc:
        log.error("sarvam_tts_request_failed", error=str(exc))
        raise RuntimeError(f"Sarvam TTS request failed: {exc}") from exc

    if not response.audios:
        log.error("sarvam_tts_empty_response", request_id=response.request_id)
        raise RuntimeError("Sarvam TTS returned no audio")

    return base64.b64decode(response.audios[0])
