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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

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


class Brand(_Strict):
    """The logo in the header and the browser tab (website W1). `logo` is an approved library photo."""
    logo: Optional[str] = None
    show_name: bool = True                                   # False = the logo already spells the name

    @field_validator("logo", mode="before")
    @classmethod
    def _logo(cls, v):
        return _asset(v)


class WhatsAppButton(_Strict):
    """The round WhatsApp button floating on every page; the number is site.contact.whatsapp (else phone)."""
    on: bool = True
    text: str = Field("", max_length=120)                    # the guest's first message; blank = the usual "Hi! I'd like to know more."


MENU_TO_RE = re.compile(r"^/[a-z0-9\-/]*(?:#[a-z][a-z0-9-]{1,39})?$")
SYSTEM_PATHS = ("/policies", "/compare", "/blog", "/my-booking", "/stays")   # pages every v2 site answers without a spec page


class MenuItem(_Strict):
    label: str = Field(min_length=1, max_length=40)
    to: str = Field(min_length=1, max_length=300)            # "/page", "/page#section-id", "/stays/<slug>", "/policies" or "https://…"

    @field_validator("to")
    @classmethod
    def _to(cls, v: str) -> str:
        if v.startswith("https://") and " " not in v:
            return v
        if not MENU_TO_RE.match(v):
            raise ValueError(f"'{v}' is not a page on this site or an https:// link")
        return v


class MenuLink(MenuItem):
    children: list[MenuItem] = Field(default_factory=list, max_length=8)    # one level of drop-down


class Menus(_Strict):
    """Header and footer links (website W1). Without `menus` the site lists the pages marked nav, as before."""
    main: list[MenuLink] = Field(default_factory=list, max_length=8)
    footer: list[MenuItem] = Field(default_factory=list, max_length=12)


# Added after drafts were already stored: left out of the stored spec while unset, so normalise(old draft) == old draft
# and the publish integrity check (website_version_service.publish) still passes for every draft saved before W1.
_OPTIONAL_SITE_KEYS = ("brand", "whatsapp_button", "menus")


class SiteInfo(_Strict):
    name: str = Field(min_length=1, max_length=80)
    tagline: str = Field("", max_length=120)
    ref_prefix: Optional[str] = Field(None, pattern=r"^[A-Z]{2,4}$")   # WhatsApp reference codes: "RT" -> RT-HOME-HERO
    contact: Contact = Contact()
    social: dict[Literal["instagram", "facebook", "youtube"], str] = Field(default_factory=dict)
    brand: Optional[Brand] = None
    whatsapp_button: Optional[WhatsAppButton] = None
    menus: Optional[Menus] = None

    @field_validator("social")
    @classmethod
    def _https(cls, v: dict) -> dict:
        for k, url in v.items():
            if not str(url).startswith("https://") or len(url) > 300:
                raise ValueError(f"{k} must be an https:// link")
        return v

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler):
        out = handler(self)
        for k in _OPTIONAL_SITE_KEYS:
            if out.get(k) is None:
                out.pop(k, None)
        return out


class Seo(_Strict):
    title: str = Field("", max_length=70)
    description: str = Field("", max_length=170)


# ─── section slots: what a person or the AI may write. Everything else is bound from HAIP data. ───────────

Short = Annotated[str, Field(max_length=60)]


class HeroSlots(_Strict):
    eyebrow: Short = ""
    headline: str = Field(min_length=1, max_length=90)       # *word* = emphasis in the accent colour
    subhead: str = Field("", max_length=240)
    media: Optional[str] = None                              # empty = the first approved library photo (the video's poster)
    video: Optional[str] = None                              # "video" layout: an uploaded MP4 from the library (no sound)
    cta_label: str = Field("Plan my trip on WhatsApp", min_length=1, max_length=40)

    @field_validator("media", "video", mode="before")
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


class OfferSlots(_Strict):
    """A seasonal offer band. The discount itself is never typed: it comes from the promo code (website_promos), and its
    amount shows only in grounded price mode. An expired or used-up code hides the band's code line, not the band."""
    eyebrow: Short = ""
    heading: str = Field(min_length=1, max_length=90)
    text: str = Field("", max_length=280)
    promo: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9]{3,30}$")
    cta_label: str = Field("Check dates", min_length=1, max_length=40)


class TemplatePartSlots(_Strict):
    """A part of a stay / package page template (website W4): everything shown comes from that stay or package."""
    eyebrow: Short = ""
    heading: str = Field("", max_length=90)


SLOTS: dict[str, type[_Strict]] = {
    "hero": HeroSlots, "stays": StaysSlots, "booking": BookingSlots, "packages": PackagesSlots, "itinerary": ItinerarySlots, "gallery": GallerySlots,
    "reviews": ReviewsSlots, "faq": FaqSlots, "contact": ContactSlots, "booking-cta": BookingCtaSlots, "text": TextSlots,
    "offer": OfferSlots,
    "stay-gallery": TemplatePartSlots, "stay-details": TemplatePartSlots, "stay-rules": TemplatePartSlots, "stay-map": TemplatePartSlots,
    "stay-booking": TemplatePartSlots, "package-details": TemplatePartSlots,
}
SectionType = Literal["hero", "stays", "booking", "packages", "itinerary", "gallery", "reviews", "faq", "contact", "booking-cta", "text",
                      "offer", "stay-gallery", "stay-details", "stay-rules", "stay-map", "stay-booking", "package-details"]
TEMPLATE_KEYS = ("stay", "package")
# Site sections a template may also use (they show site-wide data); the template's own parts start with "<key>-".
TEMPLATE_SHARED = ("text", "reviews", "faq", "gallery", "booking-cta", "contact", "offer")


def template_of(section_type: str) -> Optional[str]:
    """'stay' for stay-* parts, 'package' for package-* parts, None for a normal page section."""
    return next((k for k in TEMPLATE_KEYS if section_type.startswith(f"{k}-")), None)


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


# ─── other languages (website phase 6). English is the spec itself; each extra language is a full set of the page words,
# reviewed by a person and published with the version (the approval covers it). Add a language here + in the sites app.
LANGUAGES = {"hi": "हिन्दी"}
TEXT_SLOTS = ("eyebrow", "heading", "headline", "subhead", "intro", "text", "body", "cta_label")


class PageText(_Strict):
    title: str = Field("", max_length=60)
    seo_title: str = Field("", max_length=70)
    seo_description: str = Field("", max_length=170)


class LocaleText(_Strict):
    tagline: str = Field("", max_length=120)
    pages: dict[str, PageText] = Field(default_factory=dict)              # by page slug
    sections: dict[str, dict[str, str]] = Field(default_factory=dict)     # section id -> {text slot: words}


class TemplateSpec(_Strict):
    sections: list[Section] = Field(min_length=1, max_length=20)


class Templates(_Strict):
    """Website W4: one design that makes a page per stay (/stays/<slug>) and per package (/packages/<key>)."""
    stay: Optional[TemplateSpec] = None
    package: Optional[TemplateSpec] = None

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


class SiteSpec(_Strict):
    spec_version: Literal[2]
    site: SiteInfo
    tokens: Tokens
    pages: list[PageSpec] = Field(min_length=1, max_length=12)
    i18n: dict[Literal["hi"], LocaleText] = Field(default_factory=dict)
    templates: Optional[Templates] = None          # left out when unset (pre-W4 drafts keep passing the integrity check)

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler):
        out = handler(self)
        if out.get("templates") is None:
            out.pop("templates", None)
        return out

    def _template_sections(self) -> list[tuple[str, Section]]:
        t = self.templates
        return [(k, s) for k in TEMPLATE_KEYS if t and getattr(t, k) for s in getattr(t, k).sections]

    def _check_i18n(self) -> None:
        by_id = {s.id: s for p in self.pages for s in p.sections}
        slugs = {p.slug for p in self.pages}
        for lang, loc in self.i18n.items():
            for slug in loc.pages:
                if slug not in slugs:
                    raise ValueError(f"{lang}: no page '{slug}'")
            for sid, slots in loc.sections.items():
                sec = by_id.get(sid)
                if sec is None:
                    raise ValueError(f"{lang}: no section '{sid}'")
                for slot, words in slots.items():
                    field = SLOTS[sec.type].model_fields.get(slot)
                    if slot not in TEXT_SLOTS or field is None:
                        raise ValueError(f"{lang}: '{slot}' is not a text of the {sec.type} section")
                    cap = next((m.max_length for m in field.metadata if getattr(m, "max_length", None)), 1200)
                    if len(words) > cap:
                        raise ValueError(f"{lang}: {sid}.{slot} is longer than {cap} characters")
            found = _typed_price(loc.model_dump())
            if found:
                raise ValueError(f"a price was typed into the {LANGUAGES[lang]} words ('{found}')")

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
        for page in self.pages:
            for s in page.sections:
                if template_of(s.type):
                    raise ValueError(f"'{s.type}' belongs on the {template_of(s.type)} page design, not on {page.slug}")
        for key, s in self._template_sections():
            if template_of(s.type) not in (key, None) or (template_of(s.type) is None and s.type not in TEMPLATE_SHARED):
                raise ValueError(f"the {key} page design can't use a '{s.type}' section")
        every = [s for p in self.pages for s in p.sections] + [s for _, s in self._template_sections()]
        seen: set[str] = set()
        for s in every:                                 # section ids are unique across the site: they name the WhatsApp code
            if s.id and s.id in seen:
                raise ValueError(f"two sections use the id '{s.id}'")
            if s.id:
                seen.add(s.id)
        for s in every:
            if not s.id:
                n, sid = 2, s.type
                while sid in seen:
                    sid, n = f"{s.type}-{n}", n + 1
                s.id = sid
                seen.add(sid)
        self._check_menus()
        self._check_i18n()
        return self

    def _check_menus(self) -> None:
        menus = self.site.menus
        if not menus:
            return
        problems = menu_problems([*menus.main, *(c for m in menus.main for c in m.children), *menus.footer],
                                 {p.slug: {s.id for s in p.sections} for p in self.pages})
        if problems:
            raise ValueError("; ".join(problems))


def menu_problems(items, pages: dict[str, set]) -> list[str]:
    """Menu links that go nowhere: a page this site doesn't have, or a section that isn't on that page."""
    out: list[str] = []
    for it in items:
        to = it.to if hasattr(it, "to") else it["to"]
        label = it.label if hasattr(it, "label") else it["label"]
        if to.startswith("https://"):
            continue
        path, _, anchor = to.partition("#")
        path = path.rstrip("/") or "/"
        if path in pages:
            if anchor and anchor not in pages[path]:
                out.append(f"menu link '{label}' goes to a part of {path} that isn't there")
        elif not (path in SYSTEM_PATHS or re.fullmatch(r"/(?:stays|packages)/[a-z0-9]+(?:-[a-z0-9]+)*", path)):
            out.append(f"menu link '{label}' goes to {path}, which isn't a page on this site")
    return out
