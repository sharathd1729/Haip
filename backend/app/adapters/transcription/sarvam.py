"""
Sarvam AI Speech-to-Text adapter -- Batch Job API.

Uses the official `sarvamai` SDK's batch job client (create_job -> upload_files
-> start -> wait_until_complete -> download outputs), NOT the synchronous
POST /speech-to-text real-time endpoint. The real-time endpoint hard-caps
audio at 30 seconds ("Audio duration exceeds the maximum limit of 30
seconds. Please use the batch API for longer audio files.") -- confirmed
live in production that every real call recording (multi-minute) was
rejected outright. The batch API handles recordings up to 2 hours.

Auth: API key via header  api-subscription-key: <key> (handled by the SDK)

Supported languages (BCP-47):
  hi-IN  kn-IN  ta-IN  te-IN  ml-IN  mr-IN  gu-IN  bn-IN  od-IN  pa-IN  en-IN

Model:  saarika:v2.5  (Indic-first, code-switching aware -- v2 deprecated
        by Sarvam as of July 2026, confirmed live via 400 "Model 'saarika:v2'
        has been deprecated. Please use 'saarika:v2.5' instead.")

Key advantage over Deepgram:
  - Native Hindi + code-switched (Hinglish) support
  - Accurate on Indian-accented English
  - Speaker diarisation
"""

from __future__ import annotations
import json
import os
import tempfile
import structlog
from sarvamai import SarvamAI
from app.adapters.transcription.base import TranscriptionAdapter, TranscriptResult, TranscriptTurn
from app.core.config import settings

log = structlog.get_logger()

# Batch jobs on multi-minute call recordings can take a while to process --
# generous but bounded so a stuck job doesn't hang a Celery worker forever.
_JOB_POLL_INTERVAL_SECONDS = 5
_JOB_TIMEOUT_SECONDS = 900

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
        """
        Submits a Sarvam batch job for this recording, blocks (via the SDK's
        synchronous polling) until it completes, and parses the result.

        The SDK's job client is synchronous (plain httpx.Client, no asyncio) --
        that's fine here since this coroutine already runs inside its own
        dedicated event loop per Celery task (see workers/tasks/transcribe.py's
        _run_async), with nothing else to interleave with.
        """
        lang = _LANG_MAP.get(language_hint, language_hint)
        client = SarvamAI(api_subscription_key=self._api_key)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "recording.wav")
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)

            job = client.speech_to_text_job.create_job(
                model="saarika:v2.5",
                language_code=lang,
                with_timestamps=True,
                with_diarization=True,
            )
            job.upload_files([audio_path])
            job.start()
            job.wait_until_complete(
                poll_interval=_JOB_POLL_INTERVAL_SECONDS,
                timeout=_JOB_TIMEOUT_SECONDS,
            )

            if not job.is_successful():
                results = job.get_file_results()
                error = (results.get("failed") or [{}])[0].get("error_message", "unknown error")
                log.error("sarvam_batch_job_failed", job_id=job.job_id, error=error)
                raise RuntimeError(f"Sarvam batch job failed: {error}")

            output_dir = os.path.join(tmpdir, "output")
            job.download_outputs(output_dir)
            output_files = os.listdir(output_dir)
            if not output_files:
                raise RuntimeError("Sarvam batch job succeeded but produced no output file")

            with open(os.path.join(output_dir, output_files[0])) as f:
                payload = json.load(f)

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
        # Defensive: seen live in production as a dict rather than a list on
        # some responses, which raised KeyError(0) on timestamps[0] below.
        if not isinstance(timestamps, list) or not timestamps:
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
