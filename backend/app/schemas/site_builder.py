"""The website art director (W2): the brief, and what each AI step must return (docs/marketing-website/WEBSITE_BUILDER_V2.md).

Steps run in order and each needs the owner's approval before the next: sitemap -> wireframe -> style (3 directions, the
owner picks one, which assembles the v2 draft). These models are both the tool schema the model fills and the first check
of its answer; website_builder_service then runs the assembled result through SiteSpec validation (schemas/site_spec.py).
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.site_spec import KEY_RE, SLUG_RE, SectionType

Line = Annotated[str, Field(min_length=1, max_length=160)]
STEPS = ("sitemap", "wireframe", "style")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ─── the brief: facts HAIP fills in, plus what only the owner can say ───────────────────────────────────

class BriefOwner(_Strict):
    goals: list[Line] = Field(default_factory=list, max_length=6)         # "more direct WhatsApp enquiries for weekends"
    audience: str = Field("", max_length=300)
    tone: str = Field("", max_length=200)
    must_haves: list[Line] = Field(default_factory=list, max_length=8)    # "show the day-by-day route"
    avoid: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=12)


class BriefIn(_Strict):
    owner: BriefOwner = BriefOwner()


class RunIn(_Strict):
    feedback: Optional[str] = Field(None, max_length=600)                # "Ask for changes" text; empty = first run


class ApproveIn(_Strict):
    job_id: str = Field(min_length=1, max_length=64)


class PickIn(_Strict):
    job_id: str = Field(min_length=1, max_length=64)
    index: int = Field(ge=0, le=2)


class CopyIn(_Strict):
    slug: str = Field(pattern=SLUG_RE, max_length=80)
    section_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,39}$")
    slot: Literal["eyebrow", "heading", "headline", "subhead", "intro", "text", "cta_label"]
    instruction: str = Field(min_length=3, max_length=300)


# ─── step 1: sitemap ────────────────────────────────────────────────────────────────────────────────────

class SitemapSection(_Strict):
    type: SectionType
    reason: str = Field(min_length=3, max_length=200, description="One line: why this section is on this page")


class SitemapPage(_Strict):
    slug: str = Field(pattern=SLUG_RE, max_length=80, description="'/' for home, else like '/journeys'")
    title: str = Field(min_length=1, max_length=60)
    nav: bool = True
    reason: str = Field(min_length=3, max_length=200, description="One line: what this page is for")
    sections: list[SitemapSection] = Field(min_length=1, max_length=12)


class Sitemap(_Strict):
    pages: list[SitemapPage] = Field(min_length=1, max_length=6)
    note: str = Field("", max_length=400, description="Two sentences to the owner explaining the plan")


# ─── step 2: wireframe (a SiteSpec skeleton: variants + copy, no styling) ───────────────────────────────

class WireSection(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,39}$", description="Short unique id, e.g. 'hero', 'packages'")
    type: SectionType
    variant: str = Field(min_length=1, max_length=40)
    eyebrow: Optional[str] = Field(None, max_length=60)
    heading: Optional[str] = Field(None, max_length=90)
    headline: Optional[str] = Field(None, max_length=90, description="hero only; *one word* may be starred")
    subhead: Optional[str] = Field(None, max_length=240)
    intro: Optional[str] = Field(None, max_length=280)
    text: Optional[str] = Field(None, max_length=280)
    cta_label: Optional[str] = Field(None, max_length=40)
    key: Optional[str] = Field(None, pattern=KEY_RE, description="itinerary: which itinerary key")
    keys: Optional[list[Annotated[str, Field(pattern=KEY_RE)]]] = Field(None, max_length=6, description="packages: which package keys")
    limit: Optional[int] = Field(None, ge=1, le=24)


class WirePage(_Strict):
    slug: str = Field(pattern=SLUG_RE, max_length=80)
    title: str = Field(min_length=1, max_length=60)
    nav: bool = True
    seo_title: str = Field("", max_length=70)
    seo_description: str = Field("", max_length=170)
    sections: list[WireSection] = Field(min_length=1, max_length=12)


class Wireframe(_Strict):
    pages: list[WirePage] = Field(min_length=1, max_length=6)
    note: str = Field("", max_length=400)


# ─── step 3: three style directions ─────────────────────────────────────────────────────────────────────

class StyleDirection(_Strict):
    name: str = Field(min_length=2, max_length=40, description="Evocative two-to-four word name")
    mood: str = Field(min_length=3, max_length=220, description="One line: why this look fits this business")
    palette_preset: Optional[str] = Field(None, description="A preset name, OR leave empty and give all four colours")
    ink: Optional[str] = Field(None, description="#RRGGBB text colour")
    surface: Optional[str] = Field(None, description="#RRGGBB page background")
    primary: Optional[str] = Field(None, description="#RRGGBB buttons and links")
    accent: Optional[str] = Field(None, description="#RRGGBB one accent for emphasis and rules")
    display: str
    body: str
    radius: Literal["soft", "sharp", "pill"] = "soft"
    sample_headline: str = Field(min_length=1, max_length=90)


class StyleDirections(_Strict):
    directions: list[StyleDirection] = Field(min_length=3, max_length=3)
    note: str = Field("", max_length=400)


class CopyOut(_Strict):
    text: str = Field(min_length=1, max_length=280)
