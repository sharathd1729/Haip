"""Pydantic schemas for Dograh webhook payloads and API requests."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


class DograhTranscriptTurn(BaseModel):
    speaker: Literal["agent", "caller"]
    text: str
    timestamp: float
    language: Optional[str] = None


class DograhExtractedVariables(BaseModel):
    intent: Optional[str] = None
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None
    guest_count: Optional[int] = None
    property_name: Optional[str] = None
    sentiment: Optional[str] = None
    language_detected: Optional[str] = None


class DograhCallPayload(BaseModel):
    event: str
    call_id: str
    agent_id: str
    phone_number: str
    direction: Literal["inbound", "outbound"]
    duration_seconds: int
    status: Literal["completed", "failed", "transferred", "no-answer"]
    transcript: List[DograhTranscriptTurn]
    recording_url: Optional[str] = None
    extracted_variables: DograhExtractedVariables
    ended_at: datetime
    tenant_slug: str


class VoicePlatformUpdateRequest(BaseModel):
    voice_platform: Literal["callerdesk", "acefone", "dograh"]
    dograh_agent_id: Optional[str] = None
    sip_trunk_provider: Optional[Literal["twilio", "voipms", "plivo"]] = None
    sip_trunk_number: Optional[str] = None

    @field_validator("sip_trunk_number")
    @classmethod
    def validate_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith("+") or not v[1:].isdigit():
            raise ValueError("sip_trunk_number must be E.164 format (e.g. +919876543210)")
        return v


class VoicePlatformOut(BaseModel):
    voice_platform: str
    dograh_agent_id: Optional[str] = None
    sip_trunk_provider: Optional[str] = None
    sip_trunk_number: Optional[str] = None
    webhook_url: Optional[str] = None

    class Config:
        from_attributes = True
