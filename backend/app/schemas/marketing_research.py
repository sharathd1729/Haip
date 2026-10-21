"""Marketing Studio research schemas (agency phase B; moved out of schemas/marketing.py in agency M5 to keep files short).

Competitors are public Instagram handles; posts are pasted by a person (never scraped).
"""
import re
from typing import Literal, Optional

from pydantic import Field, field_validator

from app.schemas.marketing import _Strict

# ── Research (agency phase B) ───────────────────────────────────────────────────────────────────────────────────────

_HANDLE = re.compile(r"^@?[A-Za-z0-9._]{1,30}$")
_IG_POST = re.compile(r"^https://(www\.)?instagram\.com/(p|reel|reels|tv)/[A-Za-z0-9_-]{5,}/?(\?.*)?$")


class CompetitorIn(_Strict):
    handle: str = Field(min_length=1, max_length=31)
    display_name: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=1000)
    followers: Optional[int] = Field(default=None, ge=0, le=1_000_000_000)   # typed in by a person (source=manual)

    @field_validator("handle")
    @classmethod
    def _handle(cls, v):
        if not _HANDLE.match(v):
            raise ValueError("an Instagram handle has 1-30 letters, numbers, dots or underscores")
        return v.lstrip("@").lower()


class CompetitorPostIn(_Strict):
    """A competitor post the owner saw and pasted in. Numbers are whatever they read off the app (source=manual)."""
    permalink: str = Field(max_length=300)
    caption: Optional[str] = Field(default=None, max_length=2200)
    media_type: Optional[Literal["IMAGE", "CAROUSEL_ALBUM", "VIDEO", "REELS"]] = None
    like_count: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    comments_count: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    posted_at: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}")
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("permalink")
    @classmethod
    def _link(cls, v):
        if not _IG_POST.match(v.strip()):
            raise ValueError("paste a post link like https://www.instagram.com/p/XXXX/")
        return v.strip()


class ResearchTheme(_Strict):
    name: str = Field(min_length=1, max_length=80)
    why_it_works: str = Field(min_length=1, max_length=400)
    examples: list[str] = Field(default_factory=list, max_length=5)     # permalinks from the measured data only


class ResearchBrief(_Strict):
    """AI reading of competitor data. Numbers stay in the measured block; this holds opinion only."""
    summary: str = Field(min_length=1, max_length=1500)
    themes: list[ResearchTheme] = Field(default_factory=list, max_length=8)
    formats: list[str] = Field(default_factory=list, max_length=6)
    opportunities: list[str] = Field(default_factory=list, max_length=6)
    avoid: list[str] = Field(default_factory=list, max_length=6)
    not_enough_signal: list[str] = Field(default_factory=list, max_length=5)
