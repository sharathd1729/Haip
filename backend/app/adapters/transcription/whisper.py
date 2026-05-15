"""
Self-hosted Whisper Large v3 adapter.
Used in cost-mode when monthly calls > 1k.
Calls the whisper.cpp HTTP server or runs CLI subprocess.
"""
import subprocess
import json
import tempfile
import os
from app.adapters.transcription.base import TranscriptionAdapter, TranscriptResult, TranscriptTurn
import structlog

log = structlog.get_logger()


class WhisperAdapter(TranscriptionAdapter):
    async def transcribe(self, audio_bytes: bytes, language_hint: str = "en-IN") -> TranscriptResult:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                [
                    "whisper", tmp_path,
                    "--model", "large-v3",
                    "--language", language_hint.split("-")[0],
                    "--output_format", "json",
                    "--output_dir", "/tmp",
                ],
                capture_output=True, text=True, timeout=300,
            )
            json_path = tmp_path.replace(".mp3", ".json")
            if os.path.exists(json_path):
                with open(json_path) as f:
                    data = json.load(f)
                os.unlink(json_path)
            else:
                data = {}
        except Exception as e:
            log.error("whisper_transcription_failed", error=str(e))
            return TranscriptResult(turns=[], raw_text="", provider="whisper")
        finally:
            os.unlink(tmp_path)

        segments = data.get("segments", [])
        turns = []
        raw_parts = []
        for seg in segments:
            # Whisper doesn't diarise by default; all segments attributed to "agent" initially
            turn = TranscriptTurn(
                speaker="agent",
                t0=seg.get("start", 0.0),
                t1=seg.get("end", 0.0),
                text=seg.get("text", "").strip(),
            )
            turns.append(turn)
            raw_parts.append(seg.get("text", ""))

        return TranscriptResult(
            turns=turns,
            raw_text=" ".join(raw_parts),
            language=language_hint.split("-")[0],
            provider="whisper",
            cost_usd=0.0,  # self-hosted
        )
