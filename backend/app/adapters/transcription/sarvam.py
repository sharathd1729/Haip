"""
Sarvam AI Speech-to-Text adapter.

API docs: https://docs.sarvam.ai/api-reference-docs/speech-to-text
Endpoint: POST https://api.sarvam.ai/speech-to-text

Auth: API key via header  api-subscription-key: <key>

Supported languages (BCP-47):
  hi-IN  kn-IN  ta-IN  te-IN  ml-IN  mr-IN  gu-IN  bn-IN  od-IN  pa-IN  en-IN

Model:  saarika:v2.5  (Indic-first, code-switching aware -- v2 deprecated
        by Sarvam as of July 2026, confirmed live via 400 "Model 'saarika:v2'
        has been deprecated. Please use 'saarika:v2.5' instead.")

Key advantage over Deepgram:
  - Native Hindi + code-switched (Hinglish) support
  - Accurate on Indian-accented English
  - Speaker diarisation (with_disfluencies=false gives clean turns)
"""

from __future__ import annotations
import httpx
import structlog
from app.adapters.transcription.base import TranscriptionAdapter, TranscriptResult, TranscriptTurn
from app.core.config import settings

log = structlog.get_logger()

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Language codes Sarvam accepts → map from our hint format
_LANG_MAP = {
    "hi":    "hi-IN",
    "hi-IN": "hi-IN",
    "kn":    "kn-IN",
    "kn-IN": "kn-IN",
    "ta":    "ta-IN",
    "ta-IN": "ta-IN",
    "te":    "te-IN",
    "te-IN": "te-IN",
    "ml":    "ml-IN",
    "ml-IN": "ml-IN",
    "mr":    "mr-IN",
    "mr-IN": "mr-IN",
    "gu":    "gu-IN",
    "gu-IN": "gu-IN",
    "bn":    "bn-IN",
    "bn-IN": "bn-IN",
    "en":    "en-IN",
    "en-IN": "en-IN",
    "en-US": "en-IN",
}

# Cost: ~₹1 per minute at public pricing ≈ $0.0012/min (update when official)
_COST_PER_MIN_USD = 0.0012


class SarvamAdapter(TranscriptionAdapter):
    """
    Transcribes audio using Sarvam AI saarika:v2.5.

    Best for:
      - Hindi / Hinglish calls
      - Regional Indian languages (Kannada, Tamil, Telugu, etc.)
      - Code-switched speech (Hindi + English mixed)

    Pass language_hint as BCP-47 code, e.g. "hi-IN", "kn-IN", "en-IN".
    If unknown, use "hi-IN" — saarika handles code-switching gracefully.
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or settings.SARVAM_API_KEY

    async def transcribe(
        self,
        audio_bytes: bytes,
        language_hint: str = "hi-IN",
    ) -> TranscriptResult:
        lang = _LANG_MAP.get(language_hint, language_hint)

        # Sarvam STT expects multipart/form-data
        files = {
            "file": ("audio.wav", audio_bytes, "audio/wav"),
        }
        data = {
            "language_code": lang,
            "model": "saarika:v2.5",
            "with_timestamps": "true",
            "with_disfluencies": "false",  # removes ums/ahs for cleaner transcript
        }
        headers = {
            "api-subscription-key": self._api_key,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                SARVAM_STT_URL,
                files=files,
                data=data,
                headers=headers,
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                log.error(
                    "sarvam_stt_error",
                    status=exc.response.status_code,
                    body=exc.response.text[:300],
                )
                raise

        payload = resp.json()
        return self._parse(payload, lang)

    def _parse(self, payload: dict, language: str) -> TranscriptResult:
        """
        Parse Sarvam STT response into TranscriptResult.

        Response shape (saarika:v2 with timestamps):
        {
          "transcript": "full text",
          "language_code": "hi-IN",
          "timestamps": [
            {
              "word": "hello",
              "start": 0.24,
              "end": 0.56
            }, ...
          ],
          "diarized_transcript": {           # present when diarization available
            "entries": [
              {
                "speaker": "SPEAKER_00",
                "transcript": "...",
                "start": 0.0,
                "end": 3.2
              }, ...
            ]
          }
        }
        """
        raw_text = payload.get("transcript", "")
        turns: list[TranscriptTurn] = []

        # Prefer diarized entries if available
        diarized = payload.get("diarized_transcript", {})
        entries = diarized.get("entries", []) if isinstance(diarized, dict) else []

        if entries:
            turns = self._turns_from_diarized(entries)
        else:
            # No diarization — treat as single speaker, build from timestamps
            turns = self._turns_from_timestamps(
                payload.get("timestamps", []),
                raw_text,
            )

        duration_min = (turns[-1].t1 / 60) if turns else 0
        cost = round(duration_min * _COST_PER_MIN_USD, 6)

        detected_lang = payload.get("language_code", language)

        return TranscriptResult(
            turns=turns,
            raw_text=raw_text,
            language=detected_lang,
            provider="sarvam",
            cost_usd=cost,
        )

    @staticmethod
    def _turns_from_diarized(entries: list[dict]) -> list[TranscriptTurn]:
        """Build turns from diarized_transcript entries."""
        turns = []
        # SPEAKER_00 heuristic → agent (first speaker on the call)
        # Refine by matching phone number / agent IDs later in the pipeline
        seen_speakers: dict[str, str] = {}

        for entry in entries:
            raw_speaker = entry.get("speaker", "SPEAKER_00")
            if raw_speaker not in seen_speakers:
                # First speaker encountered → agent, rest → guest
                role = "agent" if len(seen_speakers) == 0 else "guest"
                seen_speakers[raw_speaker] = role
            speaker = seen_speakers[raw_speaker]

            turns.append(TranscriptTurn(
                speaker=speaker,
                t0=float(entry.get("start", 0.0)),
                t1=float(entry.get("end", 0.0)),
                text=entry.get("transcript", "").strip(),
            ))
        return turns

    @staticmethod
    def _turns_from_timestamps(
        timestamps: list[dict],
        raw_text: str,
    ) -> list[TranscriptTurn]:
        """
        When diarization is unavailable, wrap the full transcript as one turn.
        Groups words into ~10-second chunks so the UI renders paragraph breaks.
        """
        if not timestamps:
            return [TranscriptTurn(speaker="unknown", t0=0.0, t1=0.0, text=raw_text)]

        CHUNK_SECONDS = 10.0
        turns: list[TranscriptTurn] = []
        chunk_words: list[str] = []
        chunk_start = float(timestamps[0].get("start", 0.0))
        chunk_end = chunk_start

        for tok in timestamps:
            word = tok.get("word", "")
            start = float(tok.get("start", chunk_end))
            end = float(tok.get("end", start))

            if chunk_words and (start - chunk_start) >= CHUNK_SECONDS:
                turns.append(TranscriptTurn(
                    speaker="unknown",
                    t0=chunk_start,
                    t1=chunk_end,
                    text=" ".join(chunk_words),
                ))
                chunk_words = []
                chunk_start = start

            chunk_words.append(word)
            chunk_end = end

        if chunk_words:
            turns.append(TranscriptTurn(
                speaker="unknown",
                t0=chunk_start,
                t1=chunk_end,
                text=" ".join(chunk_words),
            ))

        return turns
