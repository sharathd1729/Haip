"""Ask a manager (consults) and the owner's consult settings. Bodies are bounded; unknown keys are refused."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ConsultAnswerIn(BaseModel):
    """approve_proposed = send the AI's proposed answer as it is; edited = send ``text``; option = send option ``option_id``."""
    model_config = ConfigDict(extra="forbid")

    mode: Literal["approve_proposed", "edited", "option"]
    text: Optional[str] = Field(default=None, max_length=2000)
    option_id: Optional[str] = Field(default=None, max_length=40)
    save_to_kb: bool = False


class ConsultSettingsIn(BaseModel):
    """Owner only (PUT /ai/consult-settings); every change is audited. Texts may use {minutes}, {time} and {day}."""
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    business_start: Optional[str] = None
    business_end: Optional[str] = None
    sla_minutes: Optional[int] = Field(default=None, ge=5, le=240)
    offhours_reply_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    holding_text: Optional[str] = Field(default=None, min_length=10, max_length=400)
    holding_text_offhours: Optional[str] = Field(default=None, min_length=10, max_length=400)
    send_holding_reply: Optional[bool] = None

    @field_validator("business_start", "business_end")
    @classmethod
    def _hhmm(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _HHMM.match(v):
            raise ValueError("use HH:MM, 24-hour (for example 09:00)")
        return v
