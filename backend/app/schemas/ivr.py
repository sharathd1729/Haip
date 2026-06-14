"""Pydantic schemas for IVR call routing."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

IVRLanguage = Literal["en-IN", "hi-IN", "kn-IN", "ta-IN", "te-IN"]


def _validate_e164(v: str) -> str:
    if not _E164_RE.match(v):
        raise ValueError(f"Phone must be E.164 format (e.g. +919876543210), got: {v!r}")
    return v


class IVROptionIn(BaseModel):
    digit: int = Field(..., ge=1, le=9)
    label: str = Field(..., min_length=1, max_length=100)
    spoken_text: str = Field(..., min_length=1, max_length=500)
    route_number: str = Field(..., description="E.164 phone to transfer call to")
    department: Optional[str] = Field(None, max_length=100)

    @field_validator("route_number")
    @classmethod
    def validate_route(cls, v: str) -> str:
        return _validate_e164(v)


class IVROptionOut(IVROptionIn):
    id: str
    ivr_config_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class IVRConfigIn(BaseModel):
    greeting_text: str = Field(..., min_length=10, max_length=1000)
    language: IVRLanguage = "en-IN"
    business_hours_enabled: bool = False
    business_hours: Optional[Dict[str, Any]] = None

    # Vobiz SIP credentials — write-only (never returned in GET)
    vobiz_username: str = Field(..., min_length=1, max_length=200)
    vobiz_password: str = Field(..., min_length=1, max_length=200)
    vobiz_server: str = Field(..., min_length=1, max_length=200)
    sip_number: str = Field(..., description="E.164 SIP number from Vobiz")

    options: List[IVROptionIn] = Field(..., min_length=1, max_length=9)

    @field_validator("sip_number")
    @classmethod
    def validate_sip(cls, v: str) -> str:
        return _validate_e164(v)

    @field_validator("options")
    @classmethod
    def validate_unique_digits(cls, v: List[IVROptionIn]) -> List[IVROptionIn]:
        digits = [o.digit for o in v]
        if len(digits) != len(set(digits)):
            raise ValueError("Each digit must be unique across options")
        return v


class IVRConfigOut(BaseModel):
    id: str
    tenant_id: str
    greeting_text: str
    language: str
    business_hours_enabled: bool
    business_hours: Optional[Dict[str, Any]]
    vobiz_username: str
    vobiz_server: str
    sip_number: str
    dograh_workflow_id: Optional[str]
    dograh_phone_number_id: Optional[str]
    is_active: bool
    webhook_url: Optional[str]
    options: List[IVROptionOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IVRCallLogOut(BaseModel):
    id: str
    tenant_id: str
    call_id: Optional[str]
    dograh_call_id: Optional[str]
    digit_pressed: Optional[int]
    routed_to_department: Optional[str]
    duration_seconds: int
    called_at: datetime

    model_config = {"from_attributes": True}


class IVRAnalyticsOut(BaseModel):
    total_calls: int
    calls_by_option: Dict[str, int]
    avg_duration_seconds: float
    calls_today: int
    top_option: Optional[str]
    days: int
