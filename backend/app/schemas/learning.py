"""The learning loop's owner settings (``brand_config.learning``) and request bodies. Strict: unknown keys are refused."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LEVELS = ("watch", "suggest", "act")
Level = Literal["watch", "suggest", "act"]
# area -> (default level, highest level the owner may choose)
AREAS: dict[str, tuple[str, str]] = {
    "replies": ("act", "act"),            # wording, question order, follow-up style and timing
    "prices": ("act", "act"),             # PUBLISHED prices only; discounts only per the published discount policy
    "routes": ("act", "act"),             # published routes; Build Your Own within the driving-time limit + free vehicles
    "holds_payments": ("suggest", "suggest"),   # hold dates, payment links: a manager taps once
    "policy_rules": ("suggest", "suggest"),     # changing a price, a policy or a discount rule: owner only, never automatic
    "ads_budget": ("suggest", "suggest"),       # Marketing Studio caps already exist
}
_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentDefaults(_Strict):
    min_sample_per_arm: int = Field(default=40, ge=10, le=2000)
    max_days: int = Field(default=14, ge=3, le=60)
    stop_loss_relative: float = Field(default=0.30, gt=0, le=0.9)     # treatment worse by >= 30% (relative) ...
    stop_loss_p: float = Field(default=0.10, gt=0, le=0.5)            # ... with p < 0.10 (one-sided) -> roll back
    keep_p: float = Field(default=0.05, gt=0, le=0.2)                 # better with p < 0.05 (two-sided) -> keep


class PeakRange(_Strict):
    start: str = "12-24"      # MM-DD, inclusive
    end: str = "01-01"        # MM-DD, inclusive; may wrap the year

    @field_validator("start", "end")
    @classmethod
    def _mmdd(cls, v: str) -> str:
        if not _MMDD.match(v or ""):
            raise ValueError("use MM-DD")
        return v


class LearningSettings(_Strict):
    paused: bool = False                      # master kill switch: no experiment runs, every arm reads the base settings
    experiments_allowed: bool = False         # off = every proposal waits for a person, nothing starts by itself
    areas: dict[str, Level] = Field(default_factory=lambda: {k: v[0] for k, v in AREAS.items()})
    byo_max_drive_hours_per_day: float = Field(default=8.0, ge=2, le=14)
    peak_dates: list[PeakRange] = Field(default_factory=lambda: [PeakRange()], max_length=12)
    experiments: ExperimentDefaults = Field(default_factory=ExperimentDefaults)
    max_lessons_in_prompt: int = Field(default=5, ge=0, le=10)

    @model_validator(mode="after")
    def _areas(self):
        bad = [k for k in self.areas if k not in AREAS]
        if bad:
            raise ValueError(f"unknown area(s): {', '.join(bad)}")
        for k, (default, ceiling) in AREAS.items():
            lvl = self.areas.get(k, default)
            if LEVELS.index(lvl) > LEVELS.index(ceiling):
                raise ValueError(f"{k} can be at most '{ceiling}'")
            self.areas[k] = lvl
        return self


class ProposeIn(_Strict):
    change_type: str = Field(min_length=3, max_length=40)
    diff: dict = Field(default_factory=dict)
    title: Optional[str] = Field(default=None, max_length=300)
    target_metric: Optional[str] = Field(default=None, max_length=30)


class DecideIn(_Strict):
    note: Optional[str] = Field(default=None, max_length=300)
