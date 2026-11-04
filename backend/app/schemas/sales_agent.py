"""Owner settings of the AI sales agent and staff decisions on its pending actions."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SalesAgentSettingsIn(BaseModel):
    """Either or both. Owner only (PUT /ai/sales-agent); each change is audited."""
    model_config = ConfigDict(extra="forbid")

    price_disclosure: Optional[Literal["handoff", "grounded"]] = None
    sales_agent_mode: Optional[Literal["off", "suggest", "autopilot"]] = None


class SalesActionRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(default=None, max_length=300)


class SalesActionStayIn(BaseModel):
    """POST /sales-actions/{id}/confirm-stay: a person confirmed where the guests sleep on an overnight trip."""
    model_config = ConfigDict(extra="forbid")

    stay_name: Optional[str] = Field(default=None, max_length=120)
