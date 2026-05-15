from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TranscriptTurn:
    speaker: str    # "agent" | "guest"
    t0: float
    t1: float
    text: str


@dataclass
class TranscriptResult:
    turns: List[TranscriptTurn]
    raw_text: str
    language: Optional[str] = None
    provider: str = "unknown"
    cost_usd: float = 0.0


class TranscriptionAdapter(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, language_hint: str = "en-IN") -> TranscriptResult:
        """Transcribe audio bytes and return structured turns."""
        ...
