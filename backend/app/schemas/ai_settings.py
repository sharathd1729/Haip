"""Request body of PATCH /api/v1/settings/ai (Settings > AI switches, docs/ai/AI_SWITCHES_SPEC.md step 2)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.services.ai_features import DEFAULTS, REPLY_MODES, REPLY_THRESHOLDS


class AISettingsUpdate(BaseModel):
    """Only the switches being changed. `features`: on/off per feature in services/ai_features.DEFAULTS;
    `reply_modes`: off | shadow (draft for staff) | autonomous per reply row in REPLY_MODES."""

    model_config = ConfigDict(extra="forbid")

    features: dict[str, bool] = {}
    reply_modes: dict[str, Literal["off", "shadow", "autonomous"]] = {}
    # confidence floor for automatic replies, 0.5 - 1.0 (Instagram comments use the Instagram DM value)
    thresholds: dict[str, float] = {}

    @field_validator("features")
    @classmethod
    def _known_features(cls, v: dict) -> dict:
        unknown = sorted(set(v) - set(DEFAULTS))
        if unknown:
            raise ValueError(f"unknown AI feature(s): {', '.join(unknown)}")
        return v

    @field_validator("thresholds")
    @classmethod
    def _valid_thresholds(cls, v: dict) -> dict:
        unknown = sorted(set(v) - set(REPLY_THRESHOLDS))
        if unknown:
            raise ValueError(f"no confidence threshold for: {', '.join(unknown)}")
        if any(not (0.5 <= float(x) <= 1.0) for x in v.values()):
            raise ValueError("confidence threshold must be between 0.5 and 1.0")
        return v

    @field_validator("reply_modes")
    @classmethod
    def _known_reply_rows(cls, v: dict) -> dict:
        unknown = sorted(set(v) - set(REPLY_MODES))
        if unknown:
            raise ValueError(f"unknown reply row(s): {', '.join(unknown)}")
        return v
