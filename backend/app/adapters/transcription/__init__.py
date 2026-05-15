"""
Transcription adapter factory.

Provider priority (first match wins):
  1. Explicit `provider` argument passed to get_transcription_adapter()
  2. TRANSCRIPTION_PROVIDER env var
  3. Auto-detect: GROQ_API_KEY set → groq | DEEPGRAM_API_KEY set → deepgram | fallback → whisper (local)
"""
from app.adapters.transcription.base import TranscriptionAdapter, TranscriptResult, TranscriptTurn
from app.core.config import settings


def get_transcription_adapter(provider: str | None = None) -> TranscriptionAdapter:
    """
    Return the correct TranscriptionAdapter.

    provider values: "groq" | "deepgram" | "whisper"
    """
    chosen = (
        provider
        or settings.TRANSCRIPTION_PROVIDER
        or _auto_detect_transcription()
    )

    if chosen == "groq":
        from app.adapters.transcription.groq_whisper import GroqWhisperAdapter
        return GroqWhisperAdapter()

    if chosen == "deepgram":
        from app.adapters.transcription.deepgram import DeepgramAdapter
        return DeepgramAdapter()

    # Default: local Whisper CLI (self-hosted, free, slowest)
    from app.adapters.transcription.whisper import WhisperAdapter
    return WhisperAdapter()


def _auto_detect_transcription() -> str:
    if settings.GROQ_API_KEY:
        return "groq"
    if settings.DEEPGRAM_API_KEY:
        return "deepgram"
    return "whisper"


__all__ = ["get_transcription_adapter", "TranscriptionAdapter", "TranscriptResult", "TranscriptTurn"]
