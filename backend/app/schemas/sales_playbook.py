"""The owner's sales playbook (brand_config.sales_playbook): how the AI sells, read by the concierge prompt and the follow-up
draft prompt. Bounded and strict: unknown keys are refused, every text is capped."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_ITEM = 300


class SalesPlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_line: str = Field(default="", max_length=400)               # lead with the experience, never the price
    qualification_questions: list[str] = Field(default_factory=list, max_length=15)
    never_ask_budget_first: bool = True
    objection_answers: dict[str, str] = Field(default_factory=dict, max_length=20)
    follow_up_style: str = Field(default="", max_length=600)
    never_say_no: bool = False                                           # "the team will check and come back with the best option"
    add_value_before_discount: bool = False                              # offer a kit / experience before any discount
    rules: list[str] = Field(default_factory=list, max_length=15)        # e.g. "Recommend ONE itinerary and at most one alternative"

    @field_validator("qualification_questions", "rules")
    @classmethod
    def _items(cls, v: list[str]) -> list[str]:
        out = [s.strip() for s in v if isinstance(s, str) and s.strip()]
        if any(len(s) > _MAX_ITEM for s in out):
            raise ValueError(f"each line must be at most {_MAX_ITEM} characters")
        return out

    @field_validator("objection_answers")
    @classmethod
    def _objections(cls, v: dict[str, str]) -> dict[str, str]:
        out = {k.strip(): a.strip() for k, a in v.items() if k and k.strip() and a and a.strip()}
        if any(len(k) > 80 or len(a) > 500 for k, a in out.items()):
            raise ValueError("an objection is at most 80 characters and its answer at most 500")
        return out
