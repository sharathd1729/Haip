"""HAIP Calls app (Android): device registration, device settings and call-log upload (docs/MOBILE_CALL_TRACKING_SPEC.md, step 1)."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class WorkingHours(BaseModel):
    """Local time in the workspace timezone. start > end means an overnight shift (22:00-06:00)."""
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("use HH:MM, 24-hour")
        return v


class DeviceSettings(BaseModel):
    # "Unknown numbers are enquiries": working_hours (default) = on inside the staff member's working hours, off outside;
    # always / never. With no working hours set, working_hours behaves like always.
    unknown_numbers: Literal["working_hours", "always", "never"] = "working_hours"
    working_hours: Optional[WorkingHours] = None
    # Numbers the staff member marked personal. Write-only: the server keeps only their SHA-256 (of the E.164 form).
    personal_numbers: list[str] = Field(default_factory=list, max_length=500)


class DeviceRegister(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    android_version: Optional[str] = Field(None, max_length=20)
    app_version: Optional[str] = Field(None, max_length=20)
    settings: Optional[DeviceSettings] = None


class DeviceCallIn(BaseModel):
    device_call_id: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=40)
    direction: Literal["in", "out"]
    started_at: AwareDatetime
    duration_sec: int = Field(ge=0, le=86400)
    answered: bool
    sim_slot: Optional[int] = Field(None, ge=0, le=9)


class DeviceCallBatch(BaseModel):
    calls: list[DeviceCallIn] = Field(min_length=1, max_length=200)
