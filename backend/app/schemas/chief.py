"""AI Executive ("chief") settings and requests (docs/ai/AI_EXECUTIVE_PLAN.md, phase E1: read-only findings + brief).

Settings live in ``tenants.brand_config.chief`` (no migration): OFF by default, owner-only (PUT /chief/settings, audited
``chief.settings_changed``); PATCH /tenants/me refuses the key.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ROLE_LABELS: dict[str, str] = {
    "sales_manager": "Sales manager",
    "concierge": "Front desk",
    "guest_relations": "Guest relations",
    "ops_manager": "Ops manager",
    "finance": "Payments",
    "revenue_manager": "Revenue manager",
    "ads_analyst": "Ads analyst",
    "it_monitor": "IT monitor",
    "hr_coach": "Team coach",
    "data_analyst": "Data analyst",
}
DISMISS_REASONS = ("not_now", "wrong", "already_handled", "too_risky", "not_worth_it")


class ChiefSettings(BaseModel):
    enabled: bool = False
    # Kill switch. In E1 it stops the AI explanations; from E2 it also stops every action. Detection keeps running.
    paused: bool = False
    roles_off: list[str] = Field(default_factory=list)
    detectors_off: list[str] = Field(default_factory=list)

    @field_validator("roles_off")
    @classmethod
    def _roles(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in ROLE_LABELS]
        if bad:
            raise ValueError(f"unknown role: {', '.join(bad)}")
        return sorted(set(v))

    @field_validator("detectors_off")
    @classmethod
    def _detectors(cls, v: list[str]) -> list[str]:
        from app.services.chief.catalogue import BY_CODE

        bad = [c for c in v if c not in BY_CODE]
        if bad:
            raise ValueError(f"unknown detector: {', '.join(bad)}")
        return sorted(set(v))


class DismissIn(BaseModel):
    reason: Literal["not_now", "wrong", "already_handled", "too_risky", "not_worth_it"]
    note: str | None = Field(default=None, max_length=300)
