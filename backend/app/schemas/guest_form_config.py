"""The workspace's own guest details form (workspace redesign Phase 4), ``brand_config.guest_form``.

Always asked (the law, never switched off): every guest's name and nationality, an ID for each guest, passport + visa
for guests from abroad (Form C), the typed signature and consent. The owner chooses the rest: four standard questions
(off | ask | req) and up to 8 questions of their own.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Mode = Literal["off", "ask", "req"]
MAX_QUESTIONS = 8


class FormQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]{6,12}$")
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["text", "yesno", "choice", "date"]
    options: list[str] = Field(default_factory=list, max_length=8)
    required: bool = False

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("A question needs words")
        return v

    @model_validator(mode="after")
    def _options(self) -> "FormQuestion":
        opts = [" ".join(o.split())[:40] for o in self.options if o.strip()]
        if self.kind == "choice":
            if len(opts) < 2 or len(set(o.lower() for o in opts)) != len(opts):
                raise ValueError(f"'{self.label}': a pick-one question needs at least 2 different choices")
        else:
            opts = []
        self.options = opts
        return self


class GuestFormConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: Mode = "ask"
    emergency: Mode = "req"
    food: Mode = "ask"
    requests: Mode = "ask"
    questions: list[FormQuestion] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    welcome: str = Field(default="", max_length=200)
    rules_url: str = Field(default="", max_length=300)

    @field_validator("welcome")
    @classmethod
    def _welcome(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("rules_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v and (not v.startswith("https://") or any(c.isspace() for c in v) or len(v) < 12):
            raise ValueError("The house rules link must start with https://")
        return v

    @model_validator(mode="after")
    def _unique(self) -> "GuestFormConfig":
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Two questions share an id")
        return self
