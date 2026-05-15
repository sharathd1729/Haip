"""Deepgram Nova-2 transcription adapter with speaker diarisation."""
import httpx
from app.adapters.transcription.base import TranscriptionAdapter, TranscriptResult, TranscriptTurn
from app.core.config import settings
import structlog

log = structlog.get_logger()

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class DeepgramAdapter(TranscriptionAdapter):
    async def transcribe(self, audio_bytes: bytes, language_hint: str = "en-IN") -> TranscriptResult:
        params = {
            "model": "nova-2-general",
            "language": language_hint,
            "diarize": "true",
            "punctuate": "true",
            "utterances": "true",
            "detect_language": "true",
        }
        headers = {
            "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
            "Content-Type": "audio/mpeg",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(DEEPGRAM_URL, content=audio_bytes, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        turns = []
        raw_parts = []
        detected_language = None

        try:
            results = data["results"]
            detected_language = results.get("channels", [{}])[0].get("detected_language")
            utterances = results.get("utterances") or []
            for utt in utterances:
                speaker_tag = f"speaker_{utt.get('speaker', 0)}"
                # Map speaker 0 → agent, others → guest (heuristic; refined by agent_id matching later)
                speaker = "agent" if utt.get("speaker", 0) == 0 else "guest"
                turn = TranscriptTurn(
                    speaker=speaker,
                    t0=utt.get("start", 0.0),
                    t1=utt.get("end", 0.0),
                    text=utt.get("transcript", ""),
                )
                turns.append(turn)
                raw_parts.append(utt.get("transcript", ""))
        except (KeyError, IndexError) as e:
            log.warning("deepgram_parse_error", error=str(e))

        # Rough cost: ~$0.0043 per minute at Nova-2 pricing
        duration_min = (turns[-1].t1 / 60) if turns else 0
        cost = round(duration_min * 0.0043, 6)

        return TranscriptResult(
            turns=turns,
            raw_text=" ".join(raw_parts),
            language=detected_language,
            provider="deepgram",
            cost_usd=cost,
        )
