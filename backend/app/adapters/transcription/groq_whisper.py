"""
Groq Whisper Large-v3 transcription adapter.

Free tier: 7,200 seconds of audio / day.
API is OpenAI-compatible so we use plain httpx — no extra SDK needed.

Limitation: Groq Whisper does NOT support speaker diarisation.
We apply a simple turn-splitting heuristic: silence gaps > 1.5s = new turn.
The judge prompt handles calls without perfect diarisation just fine.
"""
import io
import httpx
from app.adapters.transcription.base import TranscriptionAdapter, TranscriptResult, TranscriptTurn
from app.core.config import settings
import structlog

log = structlog.get_logger()

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
SILENCE_GAP_S = 1.5   # seconds gap that marks a new "turn"


def _split_into_turns(segments: list, direction: str = "inbound") -> list[TranscriptTurn]:
    """
    Convert Whisper word/segment timestamps into speaker turns.
    Without real diarisation we alternate speakers on long silence gaps.

    First speaker is labelled by call direction, not always 'agent': on an
    outbound call the callee (guest) answers and speaks first, which
    silently reversed every attribution when this always assumed 'agent'
    spoke first (same bug confirmed on the real diarizing adapters).
    """
    if not segments:
        return []

    turns: list[TranscriptTurn] = []
    current_speaker = "guest" if direction == "outbound" else "agent"
    current_text = []
    t0 = segments[0].get("start", 0.0)
    prev_end = t0

    for seg in segments:
        seg_start = seg.get("start", prev_end)
        seg_end   = seg.get("end",   seg_start)
        text      = seg.get("text", "").strip()
        if not text:
            continue

        # Gap detected — flip speaker, save previous turn
        if seg_start - prev_end > SILENCE_GAP_S and current_text:
            turns.append(TranscriptTurn(
                speaker=current_speaker,
                t0=t0, t1=prev_end,
                text=" ".join(current_text),
            ))
            current_speaker = "guest" if current_speaker == "agent" else "agent"
            current_text = []
            t0 = seg_start

        current_text.append(text)
        prev_end = seg_end

    # Flush last turn
    if current_text:
        turns.append(TranscriptTurn(
            speaker=current_speaker,
            t0=t0, t1=prev_end,
            text=" ".join(current_text),
        ))

    return turns


class GroqWhisperAdapter(TranscriptionAdapter):
    """
    Calls Groq /v1/audio/transcriptions (Whisper Large-v3).
    Uses verbose_json format to get word-level timestamps for turn splitting.
    """

    async def transcribe(self, audio_bytes: bytes, language_hint: str = "en-IN", direction: str = "inbound") -> TranscriptResult:
        lang_code = language_hint.split("-")[0]   # "en-IN" → "en"

        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        }

        # Groq accepts multipart/form-data exactly like OpenAI Whisper
        files = {
            "file": ("audio.mp3", io.BytesIO(audio_bytes), "audio/mpeg"),
        }
        data = {
            "model": "whisper-large-v3",
            "language": lang_code,
            "response_format": "verbose_json",   # gives segments + timestamps
            "temperature": "0",
        }

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                GROQ_TRANSCRIPTION_URL,
                headers=headers,
                files=files,
                data=data,
            )
            if resp.status_code != 200:
                log.error("groq_whisper_error", status=resp.status_code, body=resp.text[:500])
                resp.raise_for_status()
            result = resp.json()

        segments  = result.get("segments", [])
        raw_text  = result.get("text", "").strip()
        language  = result.get("language", lang_code)

        turns = _split_into_turns(segments, direction=direction)

        # Cost = $0 on free tier; $0.000 111 / sec at paid tier
        duration_sec = segments[-1].get("end", 0) if segments else 0
        cost_usd = 0.0  # free tier

        log.info("groq_whisper_done",
                 duration_sec=duration_sec, turns=len(turns), language=language)

        return TranscriptResult(
            turns=turns,
            raw_text=raw_text,
            language=language,
            provider="groq_whisper",
            cost_usd=cost_usd,
        )
