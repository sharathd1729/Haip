"""SiteSpec v2: the checked plan a v2 client website is rendered from (docs/marketing-website/WEBSITE_BUILDER_V2.md).

The AI (W2) and people write a SiteSpec; code renders it (sites/ app, frontend/src/site-blocks/v2). The catalogue of section
types, variants, palettes, fonts and radii is services/website_spec_v2.json; frontend/src/site-blocks/v2/spec.json must be an
identical copy (tests/test_website_spec_v2.py compares them). Validation is strict: an unknown key, section type, variant,
source, palette value that fails WCAG AA, or a price typed into any text is rejected, never repaired. Content that changes
(packages, itineraries, photos, reviews, FAQs, prices) is never typed here: a section names its `source` and the server binds
it at render time (services/website_bindings.py).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "services" / "website_spec_v2.json"
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ASSET_RE = re.compile(r"^asset:[0-9a-fA-F\-]{36}$")
SLUG_RE = r"^/(?:[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*)?$"
KEY_RE = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


# ─── colour: WCAG 2.x contrast, the same numbers a browser audit reports ──────────────────────────────────

def _lum(hex_: str) -> float:
    h = hex_.lstrip("#")
    def ch(i: int) -> float:
        c = int(h[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(0) + 0.7152 * ch(2) + 0.0722 * ch(4)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """t of colour a over (1 - t) of colour b, like CSS color-mix(in srgb, a t%, b)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#" + "".join(f"{round(int(a[i:i + 2], 16) * t + int(b[i:i + 2], 16) * (1 - t)):02X}" for i in (0, 2, 4))


def derived(p: dict) -> dict:
    """Every colour the renderer paints with. Only these pairs are ever used for text, so checking them checks the site."""
    on_primary = max((p["ink"], p["surface"]), key=lambda c: contrast(c, p["primary"]))
    return {"ink": p["ink"], "surface": p["surface"], "primary": p["primary"], "accent": p["accent"],
            "muted": mix(p["ink"], p["surface"], 0.72), "surface_alt": mix(p["surface"], p["ink"], 0.95),
            "line": mix(p["ink"], p["surface"], 0.14), "on_primary": on_primary}


def contrast_problems(p: dict) -> list[str]:
    d = derived(p)
    rules = [("ink on surface", d["ink"], d["surface"], 4.5), ("muted text on surface", d["muted"], d["surface"], 4.5),
             ("muted text on the alternate band", d["muted"], d["surface_alt"], 4.5),
             ("primary (links, small labels) on surface", d["primary"], d["surface"], 4.5),
             ("primary on the alternate band", d["primary"], d["surface_alt"], 4.5),
             ("button text on primary", d["on_primary"], d["primary"], 4.5),
             ("accent (large text, rules) on surface", d["accent"], d["surface"], 3.0)]
    return [f"{name}: {contrast(fg, bg):.2f}:1, needs {need}:1" for name, fg, bg, need in rules if contrast(fg, bg) < need]


# ─── building blocks ──────────────────────────────────────────────────────────────────────────────────────

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _asset(v: Optional[str]) -> Optional[str]:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not ASSET_RE.match(v):
        raise ValueError("photos must be 'asset:<id>' references to your approved library")
    return v


class Palette(_Strict):
    name: str = Field(min_length=1, max_length=40, pattern=KEY_RE)
    ink: str
    surface: str
    primary: str
    accent: str

    @model_validator(mode="before")
    @classmethod
    def _preset(cls, v):
        """A palette may be named ("forest-amber") or given whole; a named preset fills in its values."""
        presets = catalogue()["palettes"]
        if isinstance(v, str):
            if v not in presets:
                raise ValueError(f"unknown palette '{v}'")
            v = {"name": v}
        if isinstance(v, dict) and set(v) == {"name"} and v.get("name") in presets:
            pre = presets[v["name"]]
            v = {"name": v["name"], **{k: pre[k] for k in ("ink", "surface", "primary", "accent")}}
        return v

    @field_validator("ink", "surface", "primary", "accent")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_RE.match(v):
            raise ValueError("colours are #RRGGBB")
        return v.upper()

    @model_validator(mode="after")
    def _aa(self):
        problems = contrast_problems(self.model_dump())
        if problems:
            raise ValueError("palette fails WCAG AA contrast: " + "; ".join(problems))
        return self


class Tokens(_Strict):
    palette: Palette
    display: str
    body: str
    radius: Literal["soft", "sharp", "pill"] = "soft"
    motion: Literal["calm"] = "calm"

    @field_validator("display")
    @classmethod
    def _display(cls, v: str) -> str:
        if v not in catalogue()["fonts"]["display"]:
            raise ValueError(f"unknown display font '{v}'")
        return v

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        if v not in catalogue()["fonts"]["body"]:
            raise ValueError(f"unknown body font '{v}'")
        return v


class Contact(_Strict):
    phone: str = Field("", max_length=40)
    whatsapp: str = Field("", max_length=40)
    email: str = Field("", max_length=120)
    address: str = Field("", max_length=300)


class SiteInfo(_Strict):
    name: str = Field(min_length=1, max_length=80)
    tagline: str = Field("", max_length=120)
    ref_prefix: Optional[str] = Field(None, pattern=r"^[A-Z]{2,4}$")   # WhatsApp reference codes: "RT" -> RT-HOME-HERO
    contact: Contact = Contact()
    social: dict[Literal["instagram", "facebook", "youtube"], str] = Field(default_factory=dict)

    @field_validator("social")
    @classmethod
    def _https(cls, v: dict) -> dict:
        for k, url in v.items():
            if not str(url).startswith("https://") or len(url) > 300:
                raise ValueError(f"{k} must be an https:// link")
        return v


class Seo(_Strict):
    title: str = Field("", max_length=70)
    description: str = Field("", max_length=170)


# ─── section slots: what a person or the AI may write. Everything else is bound from HAIP data. ───────────

Short = Annotated[str, Field(max_length=60)]


class HeroSlots(_Strict):
    eyebrow: Short = ""
    headline: str = Field(min_length=1, max_length=90)       # *word* = emphasis in the accent colour
    subhead: str = Field("", max_length=240)
    media: Optional[str] = None                              # empty = the first approved library photo
    cta_label: str = Field("Plan my trip on WhatsApp", min_length=1, max_length=40)

    @field_validator("media", mode="before")
    @classmethod
    def _media(cls, v):
        return _asset(v)


class StaysSlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    intro: str = Field("", max_length=280)
    limit: int = Field(6, ge=1, le=12)


class BookingSlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    intro: str = Field("", max_length=280)
    cta_label: str = Field("Send my dates", min_length=1, max_length=40)


class PackagesSlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    intro: str = Field("", max_length=280)
    keys: list[str] = Field(default_factory=list, max_length=6)   # empty = every published retail package (max 6)

    @field_validator("keys")
    @classmethod
    def _keys(cls, v: list[str]) -> list[str]:
        if any(not re.match(KEY_RE, k) for k in v):
            raise ValueError("package keys are lower-case-with-dashes")
        return list(dict.fromkeys(v))


class ItinerarySlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    intro: str = Field("", max_length=280)
    key: Optional[str] = Field(None, pattern=KEY_RE)               # empty = the first published itinerary


class GallerySlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    media: list[str] = Field(default_factory=list, max_length=24)  # empty = approved library photos, newest first
    limit: int = Field(9, ge=3, le=24)

    @field_validator("media", mode="before")
    @classmethod
    def _media(cls, v):
        return list(dict.fromkeys(x for x in (_asset(i) for i in (v or [])) if x))


class ReviewsSlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    limit: int = Field(6, ge=1, le=12)


class FaqSlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    limit: int = Field(8, ge=1, le=20)


class ContactSlots(_Strict):
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    text: str = Field("", max_length=280)
    show_map: bool = True


class BookingCtaSlots(_Strict):
    heading: str = Field("", max_length=90)
    text: str = Field("", max_length=280)
    cta_label: str = Field("Plan my trip on WhatsApp", min_length=1, max_length=40)


class TextSlots(_Strict):
    """"Your own text": anything the owner wants to say that HAIP has no data for (house rules, the story, directions)."""
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)
    body: str = Field("", max_length=1200)                   # blank lines = new paragraphs
    media: Optional[str] = None                              # the "with-photo" layout's photo; empty = no photo

    @field_validator("media", mode="before")
    @classmethod
    def _media(cls, v):
        return _asset(v)


SLOTS: dict[str, type[_Strict]] = {
    "hero": HeroSlots, "stays": StaysSlots, "booking": BookingSlots, "packages": PackagesSlots, "itinerary": ItinerarySlots, "gallery": GallerySlots,
    "reviews": ReviewsSlots, "faq": FaqSlots, "contact": ContactSlots, "booking-cta": BookingCtaSlots, "text": TextSlots,
}
SectionType = Literal["hero", "stays", "booking", "packages", "itinerary", "gallery", "reviews", "faq", "contact", "booking-cta", "text"]


def _typed_price(obj) -> Optional[str]:
    from app.services.price_policy import detect_price
    if isinstance(obj, str):
        return detect_price(obj)
    if isinstance(obj, dict):
        return next((p for p in (_typed_price(v) for v in obj.values()) if p), None)
    if isinstance(obj, list):
        return next((p for p in (_typed_price(v) for v in obj) if p), None)
    return None


class Section(_Strict):
    id: Optional[str] = Field(None, pattern=r"^[a-z][a-z0-9-]{1,39}$")   # filled in by SiteSpec when missing
    type: SectionType
    variant: str
    slots: dict = Field(default_factory=dict)
    source: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        sec = catalogue()["sections"][self.type]
        if self.variant not in sec["variants"]:
            raise ValueError(f"unknown variant '{self.variant}' for {self.type} (one of {', '.join(sec['variants'])})")
        if self.source is None:
            self.source = sec["source"]
        elif self.source != sec["source"]:
            raise ValueError(f"{self.type} reads from '{sec['source']}', not '{self.source}'")
        self.slots = SLOTS[self.type].model_validate(self.slots).model_dump(mode="json")
        found = _typed_price(self.slots)
        if found:
            raise ValueError(f"a price was typed into the {self.type} text ('{found}'): prices come only from live HAIP data")
        return self


class PageSpec(_Strict):
    slug: str = Field(pattern=SLUG_RE, max_length=80)
    title: str = Field(min_length=1, max_length=60)
    nav: bool = True
    seo: Seo = Seo()
    sections: list[Section] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _seo_text(self):
        found = _typed_price(self.seo.model_dump())
        if found:
            raise ValueError(f"a price was typed into the search preview of {self.slug} ('{found}')")
        return self


class SiteSpec(_Strict):
    spec_version: Literal[2]
    site: SiteInfo
    tokens: Tokens
    pages: list[PageSpec] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _site_rules(self):
        slugs = [p.slug for p in self.pages]
        if len(set(slugs)) != len(slugs):
            raise ValueError("two pages use the same address")
        if "/" not in slugs:
            raise ValueError("the site needs a home page (slug '/')")
        found = _typed_price(self.site.model_dump())
        if found:
            raise ValueError(f"a price was typed into the site details ('{found}')")
        seen: set[str] = set()
        for page in self.pages:                         # section ids are unique across the site: they name the WhatsApp code
            for s in page.sections:
                if s.id and s.id in seen:
                    raise ValueError(f"two sections use the id '{s.id}'")
                if s.id:
                    seen.add(s.id)
        for page in self.pages:
            for s in page.sections:
                if not s.id:
                    n, sid = 2, s.type
                    while sid in seen:
                        sid, n = f"{s.type}-{n}", n + 1
                    s.id = sid
                    seen.add(sid)
        return self
