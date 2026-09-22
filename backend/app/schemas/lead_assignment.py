"""Lead assignment settings -- how new leads get an owner.

One main method (like the IVR routing strategy) plus optional rules that sit
on top of it. Stored as JSON on tenants.lead_assignment_config.
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

AssignMode = Literal["manual", "round_robin", "balanced"]

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class LeadAssignmentConfig(BaseModel):
    # manual      -- nobody is auto-assigned; the first agent to reply or call
    #                claims the lead.
    # round_robin -- next available agent in turn.
    # balanced    -- the available agent with the fewest open, uncontacted leads.
    mode: AssignMode = "manual"
    # A guest who enquired before goes back to the agent who handled them.
    returning_guest_same_agent: bool = False
    # The agent who answers a guest's call owns the lead.
    call_answerer_owns: bool = False
    # Reassign if the owner hasn't contacted the lead within N minutes.
    reassign_if_not_contacted: bool = False
    reassign_after_minutes: int = Field(default=30, ge=5, le=24 * 60)
    # Only auto-assign between these hours (tenant timezone); leads arriving
    # outside wait unassigned and are assigned at opening time.
    working_hours_only: bool = False
    hours_start: str = "09:00"
    hours_end: str = "21:00"

    @field_validator("hours_start", "hours_end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v or ""):
            raise ValueError("Use 24-hour HH:MM, e.g. 09:00")
        return v


class AssignableAgent(BaseModel):
    id: str
    name: str
    role: str
    takes_leads: bool
    open_uncontacted: int = 0


class LeadAssignmentSettings(LeadAssignmentConfig):
    agents: list[AssignableAgent] = []
    unassigned_open: int = 0


class LeadAssignmentUpdate(BaseModel):
    config: Optional[LeadAssignmentConfig] = None
    # {user_id: takes_leads}
    agents: Optional[dict[str, bool]] = None
