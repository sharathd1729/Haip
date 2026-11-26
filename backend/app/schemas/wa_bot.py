"""WhatsApp hours and welcome settings (services/wa_bot_settings.py), stored in ``tenants.brand_config.wa_bot``."""
from __future__ import annotations

from datetime import date as Date
from typing import Optional

from pydantic import BaseModel, Field, field_validator

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class DayHours(BaseModel):
    closed: bool = False
    open: str = Field("09:00", pattern=HHMM)
    close: str = Field("21:00", pattern=HHMM)   # at or before `open` = past midnight; equal = open all day


class Weekly(BaseModel):
    mon: DayHours = DayHours()
    tue: DayHours = DayHours()
    wed: DayHours = DayHours()
    thu: DayHours = DayHours()
    fri: DayHours = DayHours()
    sat: DayHours = DayHours()
    sun: DayHours = DayHours()


class Holiday(BaseModel):
    date: Date
    label: str = Field("", max_length=40)


class Hours(BaseModel):
    weekly: Weekly = Weekly()
    holidays: list[Holiday] = Field(default_factory=list, max_length=60)

    @field_validator("holidays")
    @classmethod
    def _one_per_date(cls, v: list[Holiday]) -> list[Holiday]:
        return sorted({h.date: h for h in v}.values(), key=lambda h: h.date)


class Welcome(BaseModel):
    enabled: bool = False
    text: str = Field(min_length=1, max_length=1024)
    buttons: list[str] = Field(default_factory=list, max_length=3)
    also_when_ai_replies: bool = True

    @field_validator("buttons", mode="before")
    @classmethod
    def _buttons(cls, v):
        out = [str(b).strip() for b in (v or []) if str(b or "").strip()]
        if out:
            from app.services import wa_interactive
            wa_interactive.validate({"kind": "buttons", "buttons": out})   # Meta's limits: 20 characters, all different
        return out


class LocationReply(BaseModel):
    enabled: bool = False
    text: str = Field(min_length=1, max_length=1024)
    map_link: str = Field("", max_length=500)

    @field_validator("map_link")
    @classmethod
    def _https(cls, v: str) -> str:
        v = (v or "").strip()
        if v and (not v.startswith("https://") or " " in v):
            raise ValueError("The map link must start with https://")
        return v


class OptConfirm(BaseModel):
    custom: bool = True          # off = the approved templates haip_optout_confirm_v1 / haip_optin_confirm_v1 (the old behaviour)
    stop_text: str = Field(min_length=1, max_length=1024)
    start_text: str = Field(min_length=1, max_length=1024)


class WaBotSettingsIn(BaseModel):
    """PUT body: each section given replaces that section; sections left out stay as they are."""
    hours: Optional[Hours] = None
    welcome: Optional[Welcome] = None
    location_reply: Optional[LocationReply] = None
    opt_confirm: Optional[OptConfirm] = None
