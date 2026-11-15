"""Reel hook options + spoken script (Instagram toolkit phase 2; services/marketing_hooks.py).

What the AI returns is validated here before anything is stored. Scores, blocks, timings and the formula a person
picked are computed by code (marketing_hooks), never taken from the model.
"""

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HookDraft(_Strict):
    formula_id: int = Field(ge=1, le=26)  # marketing_hooks.json `hooks[].id`
    spoken: str = Field(min_length=3, max_length=160)  # the first thing said
    on_screen: str = Field(min_length=1, max_length=60)  # the first thing read; six words or fewer


class ScriptLine(_Strict):
    line: str = Field(min_length=1, max_length=220)  # what is said
    shot: str = Field(min_length=1, max_length=200)  # what is on screen while it is said


class ReelHookDraft(_Strict):
    options: list[HookDraft] = Field(min_length=3, max_length=3)
    script: list[ScriptLine] = Field(min_length=2, max_length=10)  # after the hook: stake, body, payoff + the one ask
