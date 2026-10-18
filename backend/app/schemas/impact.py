"""Request bodies of the impact view (endpoints/impact.py)."""
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


class BaselineIn(BaseModel):
    value: float = Field(ge=0, le=1_000_000_000_000)
    period_label: str = Field(min_length=1, max_length=80, description="The period the figure describes, in the owner's words")
    source_note: Optional[str] = Field(default=None, max_length=500, description="Where the figure comes from")

    @field_validator("period_label")
    @classmethod
    def _period(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Say which period the figure describes")
        return v

    @field_validator("source_note")
    @classmethod
    def _note(cls, v: Optional[str]) -> Optional[str]:
        return _clean(v)


class ImpactSettingsIn(BaseModel):
    go_live_date: date
    window_days: int = Field(default=30, ge=7, le=180)


class CaseStudyPublishIn(BaseModel):
    slug: str = Field(min_length=2, max_length=40)
    brand_name: str = Field(min_length=1, max_length=80)
    headline: Optional[str] = Field(default=None, max_length=160)
    summary: Optional[str] = Field(default=None, max_length=1200)
    include_revenue: bool = False

    @field_validator("brand_name")
    @classmethod
    def _brand(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give the brand name to show")
        return v

    @field_validator("headline", "summary")
    @classmethod
    def _texts(cls, v: Optional[str]) -> Optional[str]:
        return _clean(v)
