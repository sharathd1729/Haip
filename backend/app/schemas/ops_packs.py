"""Packs as data + self check-in (Ops 2, gap 7): request bodies for /ops/pack/* and /ops/properties/{id}/self-check-in."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ops import DUTIES, INCIDENT_CATEGORIES

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
SOURCES = ("staff", "system", "manager")


class ChecklistItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str = Field(min_length=1, max_length=200)
    critical: bool = False
    source: str = "staff"
    photo: bool = False

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError("key: lower-case letters, digits and _, starting with a letter (max 40)")
        return v

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if v not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        return v


class ChecklistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    items: list[ChecklistItemIn] = Field(min_length=1, max_length=40)

    @field_validator("items")
    @classmethod
    def _unique(cls, v: list[ChecklistItemIn]) -> list[ChecklistItemIn]:
        keys = [i.key for i in v]
        if len(keys) != len(set(keys)):
            raise ValueError("each checklist line needs its own key")
        return v


class IssueTypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str = Field(min_length=1, max_length=80)
    category: str

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError("key: lower-case letters, digits and _")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in INCIDENT_CATEGORIES:
            raise ValueError(f"category must be one of {INCIDENT_CATEGORIES}")
        return v


class AddonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str = Field(min_length=1, max_length=80)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError("key: lower-case letters, digits and _")
        return v


class TimingIn(BaseModel):
    """Only the hours (or the day) change; when/to/built belong to the pack."""

    model_config = ConfigDict(extra="forbid")
    hours: int | None = Field(default=None, ge=1, le=240)
    day: int | None = Field(default=None, ge=1, le=30)


class PackConfigPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow: str | None = None
    duties: list[str] | None = Field(default=None, max_length=len(DUTIES))
    issue_types: list[IssueTypeIn] | None = Field(default=None, max_length=30)
    paperwork: list[str] | None = Field(default=None, max_length=12)
    addons: list[AddonIn] | None = Field(default=None, max_length=30)
    auto_messages: dict[str, TimingIn] | None = None

    @field_validator("duties")
    @classmethod
    def _duties(cls, v):
        if v is not None and any(d not in DUTIES for d in v):
            raise ValueError(f"duties must be from {DUTIES}")
        return v

    @field_validator("paperwork")
    @classmethod
    def _paperwork(cls, v):
        if v is not None and any(not (1 <= len(p.strip()) <= 80) for p in v):
            raise ValueError("each paperwork line is 1-80 characters")
        return v


class SelfCheckInPut(BaseModel):
    """Values never appear in repr (logs, errors). An empty string clears one; a missing field is left as it is."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    enabled: bool | None = None
    steps: str | None = Field(default=None, max_length=1500, repr=False)
    lock_code: str | None = Field(default=None, max_length=40, repr=False)
    key_box: str | None = Field(default=None, max_length=200, repr=False)
