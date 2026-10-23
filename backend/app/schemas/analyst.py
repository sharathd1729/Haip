"""The AI business analyst: owner settings (``brand_config.analyst``), request bodies and the structured brief.

Strict models: unknown keys are refused and every text is capped, so stored settings never grow fields nobody reads.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

KINDS = ("daily_pulse", "weekly_brief", "monthly_review")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Schedule(_Strict):
    on: bool = True
    time: str = "09:00"                       # local time (IST), HH:MM

    @field_validator("time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v or ""):
            raise ValueError("time must be HH:MM (24 h)")
        return v


class Delivery(_Strict):
    email: bool = False                       # Resend, to opted-in owners/managers
    whatsapp: bool = False                    # template haip_analyst_brief_v1, only once Meta approved it


class AnalystSettings(_Strict):
    enabled: bool = False
    daily: Schedule = Field(default_factory=lambda: Schedule(time="09:00"))
    weekly: Schedule = Field(default_factory=lambda: Schedule(time="08:30"))
    monthly: Schedule = Field(default_factory=lambda: Schedule(time="08:30"))
    delivery: Delivery = Field(default_factory=Delivery)


class RunIn(_Strict):
    kind: Literal["daily_pulse", "weekly_brief", "monthly_review"] = "weekly_brief"


class AskIn(_Strict):
    report_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=3, max_length=500)


class AssignRecIn(_Strict):
    user_id: str = Field(min_length=1, max_length=64)


# ── the brief the model must return (validated in code, numbers grounded in the facts) ─────────────────────

class Recommendation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str = Field(max_length=400)
    owner_role: Literal["owner", "manager", "sales", "marketing", "ai"] = "manager"
    due: str = Field(default="this week", max_length=40)
    expected_effect: str = Field(default="", max_length=300)
    change_proposal: Optional[str] = Field(default=None, max_length=40)      # a learning.catalogue change type


class Brief(BaseModel):
    model_config = ConfigDict(extra="ignore")
    headline: str = Field(default="", max_length=300)
    working: list[str] = Field(default_factory=list, max_length=8)
    not_working: list[str] = Field(default_factory=list, max_length=8)
    why_lost: str = Field(default="", max_length=800)
    why_dms_not_leads: str = Field(default="", max_length=800)
    team: str = Field(default="", max_length=800)
    demand: str = Field(default="", max_length=800)
    money: str = Field(default="", max_length=800)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=8)
    last_week_followup: str = Field(default="", max_length=800)
