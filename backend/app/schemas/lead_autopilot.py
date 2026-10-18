"""Lead autopilot settings + actions (see services/lead_autopilot_service.py)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

AutopilotMode = Literal["off", "suggest", "autopilot"]


class AutopilotSettings(BaseModel):
    """tenants.brand_config["lead_autopilot"]. Defaults = today's behaviour: suggestions only, nothing moves by itself."""
    mode: AutopilotMode = "suggest"
    # An AI (not rule) decision is applied automatically only at or above this confidence, and only with valid evidence.
    ai_threshold: float = Field(0.85, ge=0.5, le=1.0)
    # Run the AI classifier for leads no rule decides (after a call or a burst of messages).
    ai_enabled: bool = True
    # No reply from the guest for this many days after the team's last contact -> Lost (no response).
    silence_days: int = Field(14, ge=3, le=90)
    # A quote sent and no reply for this many days -> Lost (no response), unless the quote/payment link is still live.
    quote_silence_days: int = Field(7, ge=2, le=60)
    # This many unanswered outbound calls in a row, across at least two days -> RNR.
    unanswered_calls: int = Field(3, ge=2, le=10)


class AutopilotSettingsUpdate(BaseModel):
    mode: Optional[AutopilotMode] = None
    ai_threshold: Optional[float] = Field(None, ge=0.5, le=1.0)
    ai_enabled: Optional[bool] = None
    silence_days: Optional[int] = Field(None, ge=3, le=90)
    quote_silence_days: Optional[int] = Field(None, ge=2, le=60)
    unanswered_calls: Optional[int] = Field(None, ge=2, le=10)


class AutopilotSettingsOut(AutopilotSettings):
    applied_30d: int = 0
    undone_30d: int = 0
    suggested_open: int = 0


class UndoRequest(BaseModel):
    event_id: str


class PinRequest(BaseModel):
    pinned: bool
