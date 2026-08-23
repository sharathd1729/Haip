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


def generate_speech(
    text: str,
    speaker: str = "anushka",
    target_language_code: str = "en-IN",
) -> bytes:
    """
    Synthesize `text` via Sarvam's bulbul:v2 TTS model, returning MP3 bytes.
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
        )
    except Exception as exc:
        log.error("sarvam_tts_request_failed", error=str(exc))
        raise RuntimeError(f"Sarvam TTS request failed: {exc}") from exc

    if not response.audios:
        log.error("sarvam_tts_empty_response", request_id=response.request_id)
        raise RuntimeError("Sarvam TTS returned no audio")

    return base64.b64decode(response.audios[0])
