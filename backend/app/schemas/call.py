from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Any


class TranscriptTurn(BaseModel):
    speaker: str      # agent | guest
    t0: float
    t1: float
    text: str


class CallOut(BaseModel):
    id: str
    tenant_id: str
    guest_id: Optional[str] = None
    inquiry_id: Optional[str] = None
    agent_id: Optional[str] = None
    property_id: Optional[str] = None
    ivr_provider: str
    direction: str
    from_number: str
    to_number: str
    duration_seconds: int = 0
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    transcription_status: str = "pending"
    ai_score_status: str = "pending"
    ai_summary: Optional[str] = None
    ai_disposition: Optional[str] = None
    ai_next_action: Optional[str] = None
    ai_score: Optional[float] = None
    human_disposition: Optional[str] = None
    detected_language: Optional[str] = None

    class Config:
        from_attributes = True


class CallDetailOut(CallOut):
    transcript_turns: Optional[List[TranscriptTurn]] = None
    score: Optional[Any] = None  # CallScoreOut, populated by endpoint


class WrapUpRequest(BaseModel):
    disposition: str
    summary: Optional[str] = None
    next_action: Optional[str] = None


class ClickToCallRequest(BaseModel):
    guest_number: str
    agent_number: str
    inquiry_id: Optional[str] = None


class DispositionOverrideRequest(BaseModel):
    disposition: str
    note: Optional[str] = None
