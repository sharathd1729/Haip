"""
Sarvam AI Speech-to-Text-Translate adapter -- Batch Job API.

Uses the official `sarvamai` SDK's batch STT-TRANSLATE job client
(create_job -> upload_files -> start -> wait_until_complete -> download
outputs), NOT the plain transcribe job and NOT the synchronous
POST /speech-to-text real-time endpoint (hard-caps audio at 30s -- real
call recordings are always longer). The translate job auto-detects the
spoken language and always outputs English text/turns, regardless of
whether the call was in Hindi, Hinglish, a regional language, or English.

Confirmed live: the plain (non-translate) transcribe job returns text in
the *script* of whatever language_code is passed -- English speech
transcribed with a "hi-IN" hint came back phonetically transliterated
into Devanagari (e.g. "फॉर सिक्स पीपल" for "for six people"), unusable
for English-reading staff and worse input for downstream LLM analysis.
The translate job side-steps this entirely by always producing English.

Model: saaras:v2.5 (Sarvam's translate-capable model; auto-detects
       source language, no language_code param needed/accepted).

Auth: API key via header  api-subscription-key: <key> (handled by the SDK)
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

# Cost: ~₹1 per minute at public pricing ≈ $0.0012/min (update when official)
_COST_PER_MIN_USD = 0.0012


def _sniff_audio_extension(audio_bytes: bytes) -> str:
    """The recording bytes handed to transcribe() come straight from S3 with
    zero format conversion (see transcribe.py) -- this call was writing them
    to a file unconditionally named "recording.wav" regardless of actual
    content, even though Vobiz (the only confirmed live provider) stores
    recordings as .mp3. A decoder that trusts the extension over the real
    bytes could misread compressed MP3 frames as raw PCM. Sniffed from the
    real magic bytes rather than assumed, so this stays correct if a future
    provider genuinely sends WAV."""
    if audio_bytes[:4] == b"RIFF":
        return "wav"
    return "mp3"


class SarvamAdapter(TranscriptionAdapter):
    """
    Transcribes AND translates call audio to English using Sarvam AI's
    speech-to-text-translate batch job (saaras:v2.5).

    Best for:
      - Hindi / Hinglish / regional-language calls -- always comes back
        in English, unlike the plain transcribe job which preserves
        (and can garble into the wrong script) the spoken language.
      - Downstream LLM analysis (classify.py) working on clean English.

    language_hint is accepted for interface compatibility with other
    TranscriptionAdapter implementations but unused -- the translate job
    auto-detects the source language itself and always outputs English.
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or settings.SARVAM_API_KEY

    async def transcribe(
        self,
        audio_bytes: bytes,
        language_hint: str = "hi-IN",
        direction: str = "inbound",
    ) -> TranscriptResult:
        """
        Submits a Sarvam batch translate job for this recording, blocks
        (via the SDK's synchronous polling) until it completes, and
        parses the result.

        The SDK's job client is synchronous (plain httpx.Client, no asyncio) --
        that's fine here since this coroutine already runs inside its own
        dedicated event loop per Celery task (see workers/tasks/transcribe.py's
        _run_async), with nothing else to interleave with.
        """
        client = SarvamAI(api_subscription_key=self._api_key)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, f"recording.{_sniff_audio_extension(audio_bytes)}")
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)

            job = self._create_job(client)
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
                raise RuntimeError(f"Sarvam batch translate job failed: {error}")

            output_dir = os.path.join(tmpdir, "output")
            job.download_outputs(output_dir)
            output_files = os.listdir(output_dir)
            if not output_files:
                raise RuntimeError("Sarvam batch job succeeded but produced no output file")

            with open(os.path.join(output_dir, output_files[0])) as f:
                payload = json.load(f)

        return self._parse(payload, "en-IN", direction=direction)

    @staticmethod
    def _create_job(client):
        """Create the batch job on the configured model (settings.SARVAM_STT_MODEL).

        saaras:v3 (default, proven in production): the speech-to-text-TRANSLATE batch job; it auto-detects the spoken language and
        always returns English. Confirmed live: saaras:v2.5 collapsed a clearly two-person call onto one speaker id, v3 diarized it
        correctly; num_speakers is pinned to 2 because every HAIP call is agent + guest (left unset the model guessed 1 on short or noisy
        recordings).

        saaras:v4 (opt-in): v4 is served by the plain speech-to-text job, with translation as a MODE (mode="translate" = English out),
        and it accepts key terms (names, places, brands) to transcribe accurately. Not the default until compared on real calls.
        """
        model = (settings.SARVAM_STT_MODEL or "saaras:v3").strip()
        if model == "saaras:v4":
            kwargs: dict = {}
            terms = [t.strip() for t in (settings.SARVAM_KEYTERMS or "").split(",") if t.strip()][:50]
            if terms:
                kwargs["keyterms"] = terms
            return client.speech_to_text_job.create_job(
                model="saaras:v4", mode="translate", with_diarization=True, num_speakers=2, **kwargs,
            )
        return client.speech_to_text_translate_job.create_job(model="saaras:v3", with_diarization=True, num_speakers=2)

    def _parse(self, payload: dict, language: str, direction: str = "inbound") -> TranscriptResult:
        """
        Parse Sarvam STT response into TranscriptResult.

        Response shape confirmed live against a real saaras:v3 batch job:
        {
          "request_id": "...",
          "transcript": "full text",
          "language_code": "hi-IN",
          "language_probability": 0.9,
          "diarized_transcript": {           # present when diarization available
            "entries": [
              {
                "speaker_id": "speaker_1",   # v2.5 used "speaker" -- see _turns_from_diarized
                "transcript": "...",
                "start_time_seconds": 0.0,   # v2.5 used "start"/"end"
                "end_time_seconds": 3.2
              }, ...
            ]
          }
          # "timestamps" (word-level, used by _turns_from_timestamps below)
          # was present on older/non-diarized responses -- not observed on
          # a real v3 diarized response, kept as the no-diarization fallback
          # path since nothing here confirms it was removed outright.
        }
        """
        raw_text = payload.get("transcript", "")
        turns: list[TranscriptTurn] = []

        # Prefer diarized entries if available
        diarized = payload.get("diarized_transcript", {})
        if isinstance(diarized, dict):
            entries = diarized.get("entries", [])
        elif isinstance(diarized, list):                   # tolerate a bare list of entries (a newer model's response shape)
            entries = diarized
        else:
            entries = []
        log.info("sarvam_output_shape", model=settings.SARVAM_STT_MODEL, keys=sorted(payload.keys())[:12], diarized_entries=len(entries))

        if entries:
            turns = self._turns_from_diarized(entries, direction=direction)
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
    def _turns_from_diarized(entries: list[dict], direction: str = "inbound") -> list[TranscriptTurn]:
        """Build turns from diarized_transcript entries.

        saaras:v3 renamed the per-entry fields from v2.5's "speaker"/
        "start"/"end" to "speaker_id"/"start_time_seconds"/
        "end_time_seconds" (confirmed live via a real job response -- the
        old key names silently returned None for every entry under v3,
        which is what made diarization look broken even after num_speakers
        pinning and the audio-format fix; it was actually a field-name
        mismatch on top of the deprecated model). Checks the new key first,
        falls back to the old one so this survives either response shape.

        Real bug, confirmed live (Ratha, Sep 2026): "first speaker heard =
        agent" is not direction-invariant. On an inbound call the agent/IVR
        greeting usually comes first, so that heuristic tends to hold; on an
        outbound call the callee (guest) is the one who answers and speaks
        first ("Hello?"), which silently reversed every attribution on
        agent-initiated calls -- every downstream reader (classify/judge/
        wrap-up prompts, the QA rubric, the transcript UI) trusts this label
        as ground truth with no correction step. Flip which cluster is
        "agent" based on call direction instead of always trusting order."""
        first_role, second_role = ("guest", "agent") if direction == "outbound" else ("agent", "guest")
        turns = []
        # First speaker encountered → first_role (direction-based heuristic)
        # Refine by matching phone number / agent IDs later in the pipeline
        seen_speakers: dict[str, str] = {}

        def _speaker_id(entry: dict) -> str:
            return entry.get("speaker_id") or entry.get("speaker") or "speaker_1"

        # Diarization sometimes collapses the whole call onto a single raw
        # speaker id (crossed/noisy audio, very short calls, or the
        # deprecated model -- confirmed live) -- confirmed live: a call
        # clearly alternating between two people came back entirely
        # labeled "Agent" because every entry had the same raw speaker id,
        # and "first speaker == agent" is trivially true when there's only
        # ever one id. Label honestly as "unknown" instead of guessing when
        # diarization didn't actually distinguish anyone.
        unique_raw_speakers = {_speaker_id(entry) for entry in entries}
        diarization_worked = len(unique_raw_speakers) > 1

        for entry in entries:
            if diarization_worked:
                raw_speaker = _speaker_id(entry)
                if raw_speaker not in seen_speakers:
                    # First speaker encountered → first_role, rest → second_role
                    role = first_role if len(seen_speakers) == 0 else second_role
                    seen_speakers[raw_speaker] = role
                speaker = seen_speakers[raw_speaker]
            else:
                speaker = "unknown"

            t0 = entry.get("start_time_seconds", entry.get("start", 0.0))
            t1 = entry.get("end_time_seconds", entry.get("end", 0.0))
            turns.append(TranscriptTurn(
                speaker=speaker,
                t0=float(t0 or 0.0),
                t1=float(t1 or 0.0),
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
