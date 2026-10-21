"""Marketing Studio schemas (docs/marketing-website/PHASE0_AUDIT.md §7.3).

Every content version, plan and audit assessment is validated against these models before it is stored, whether a
person wrote it or the AI did. Limits follow Instagram's published caps (caption 2,200 characters, 30 hashtags,
carousel 2-10 items, story frames one at a time).
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTENT_KINDS = ("post", "carousel", "story", "promo")
CHANNELS = ("instagram",)

# Item lifecycle in Phase 1 (no external publishing yet): draft -> in_review -> approved | rejected; any edit -> draft.
ITEM_STATUSES = ("draft", "in_review", "approved", "rejected", "archived", "scheduled", "published")
GENERATION_STATUSES = ("idle", "pending", "failed")

CAPTION_MAX = 2200
HASHTAGS_MAX = 30
_HASHTAG = re.compile(r"^#?[\wऀ-ॿ]{1,100}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _clean_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = t.strip()
        if not _HASHTAG.match(t):
            raise ValueError(f"not a hashtag: {t[:40]!r}")
        t = "#" + t.lstrip("#")
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


# ── Business profile (stored in tenants.brand_config["business_profile"]) ──────────────────────────────────────────

class SocialLinks(_Strict):
    instagram: Optional[str] = Field(default=None, max_length=200)
    facebook: Optional[str] = Field(default=None, max_length=200)
    website: Optional[str] = Field(default=None, max_length=200)
    youtube: Optional[str] = Field(default=None, max_length=200)

    @field_validator("*")
    @classmethod
    def _https_only(cls, v):
        if v and not (v.startswith("https://") or v.startswith("@")):
            raise ValueError("use an https:// link or an @handle")
        return v


class BusinessProfile(_Strict):
    """What the AI may say about the business. `Tenant.brand_name` stays the canonical name and
    `brand_config.branding_theme` the visual source; this adds only what neither holds."""
    tagline: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    audience: Optional[str] = Field(default=None, max_length=600)
    tone: Optional[str] = Field(default=None, max_length=300)
    usps: list[str] = Field(default_factory=list, max_length=10)
    avoid: list[str] = Field(default_factory=list, max_length=20)          # words/claims the brand never uses
    languages: list[str] = Field(default_factory=lambda: ["en"], max_length=5)
    city: Optional[str] = Field(default=None, max_length=80)
    region: Optional[str] = Field(default=None, max_length=80)
    contact_phone: Optional[str] = Field(default=None, max_length=20)
    contact_email: Optional[str] = Field(default=None, max_length=120)
    gstin: Optional[str] = Field(default=None, pattern=r"^[0-9A-Z]{15}$")
    socials: SocialLinks = Field(default_factory=SocialLinks)
    default_hashtags: list[str] = Field(default_factory=list, max_length=HASHTAGS_MAX)

    @field_validator("usps", "avoid")
    @classmethod
    def _short_items(cls, v):
        for item in v:
            if len(item) > 200:
                raise ValueError("each item must be at most 200 characters")
        return [i.strip() for i in v if i.strip()]

    @field_validator("default_hashtags")
    @classmethod
    def _tags(cls, v):
        return _clean_hashtags(v)


# ── Content payloads (one model per kind) ───────────────────────────────────────────────────────────────────────────

class MediaRef(_Strict):
    asset_id: Optional[str] = Field(default=None, max_length=64)   # media_assets.id; None = still needs a photo
    alt_text: Optional[str] = Field(default=None, max_length=300)


class Design(_Strict):
    """How text is drawn on the photos (services/marketing_render.py). Part of the payload, so an approval covers the
    exact look that will be posted: overlay = dark fade with white text; panel = brand-coloured band; photo = no text."""
    style: Literal["overlay", "panel", "photo"] = "overlay"
    colour: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class _Captioned(_Strict):
    caption: str = Field(min_length=1, max_length=CAPTION_MAX)
    hashtags: list[str] = Field(default_factory=list)
    # Posted as the first comment (e.g. a question that invites replies); where the hashtags go is the publisher's choice.
    first_comment: Optional[str] = Field(default=None, max_length=CAPTION_MAX)

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, v):
        return _clean_hashtags(v)

    @model_validator(mode="after")
    def _limits(self):
        if len(self.hashtags) > HASHTAGS_MAX:
            raise ValueError(f"at most {HASHTAGS_MAX} hashtags")
        tail = " ".join(self.hashtags)
        if len(self.caption) + (len(tail) + 2 if tail else 0) > CAPTION_MAX:
            raise ValueError(f"caption plus hashtags must fit in {CAPTION_MAX} characters")
        return self


class PostContent(_Captioned):
    kind: Literal["post"] = "post"
    media: MediaRef = Field(default_factory=MediaRef)
    overlay_text: Optional[str] = Field(default=None, max_length=120)
    design: Optional[Design] = None


class CarouselSlide(_Strict):
    media: MediaRef = Field(default_factory=MediaRef)
    headline: Optional[str] = Field(default=None, max_length=80)
    body: Optional[str] = Field(default=None, max_length=200)


class CarouselContent(_Captioned):
    kind: Literal["carousel"] = "carousel"
    slides: list[CarouselSlide] = Field(min_length=2, max_length=10)
    design: Optional[Design] = None


class StorySticker(_Strict):
    type: Literal["poll", "question", "link"]
    text: str = Field(min_length=1, max_length=80)
    options: list[str] = Field(default_factory=list, max_length=2)   # poll answers

    @model_validator(mode="after")
    def _poll_options(self):
        if self.type == "poll" and len(self.options) != 2:
            raise ValueError("a poll needs exactly two answers")
        if self.type != "poll" and self.options:
            raise ValueError("only a poll has answers")
        for o in self.options:
            if not 1 <= len(o) <= 25:
                raise ValueError("poll answers must be 1-25 characters")
        return self


class StoryFrame(_Strict):
    media: MediaRef = Field(default_factory=MediaRef)
    text: Optional[str] = Field(default=None, max_length=120)
    cta: Optional[str] = Field(default=None, max_length=40)
    sticker: Optional[StorySticker] = None
    shot_note: Optional[str] = Field(default=None, max_length=200)   # what to film or photograph for this frame


class StoryContent(_Strict):
    """One ask per sequence: at most one poll/question and at most one link sticker across all frames."""
    kind: Literal["story"] = "story"
    frames: list[StoryFrame] = Field(min_length=1, max_length=10)
    design: Optional[Design] = None

    @model_validator(mode="after")
    def _one_ask(self):
        types = [f.sticker.type for f in self.frames if f.sticker]
        if sum(t in ("poll", "question") for t in types) > 1:
            raise ValueError("use at most one poll or question per story sequence")
        if types.count("link") > 1:
            raise ValueError("use at most one link sticker per story sequence")
        return self


class PromoContent(_Captioned):
    kind: Literal["promo"] = "promo"
    headline: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=400)
    cta: str = Field(min_length=1, max_length=40)
    offer: Optional[str] = Field(default=None, max_length=160)
    valid_until: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    media: MediaRef = Field(default_factory=MediaRef)
    design: Optional[Design] = None


CONTENT_MODELS: dict[str, type[BaseModel]] = {
    "post": PostContent, "carousel": CarouselContent, "story": StoryContent, "promo": PromoContent,
}


def validate_content(kind: str, payload: dict) -> dict:
    """Validated, normalised payload for a kind. Raises ValueError (pydantic.ValidationError) on bad input."""
    model = CONTENT_MODELS.get(kind)
    if model is None:
        raise ValueError(f"unknown content kind: {kind}")
    return model.model_validate({**payload, "kind": kind}).model_dump(mode="json")


def strings_of(payload: dict) -> list[str]:
    """Every guest-visible string in a payload, one per field (`date` fields are not text a guest reads)."""
    parts: list[str] = []

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("asset_id", "kind", "date", "valid_until"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(payload)
    return parts


def text_of(payload: dict) -> str:
    return "\n".join(strings_of(payload))


# ── AI outputs ──────────────────────────────────────────────────────────────────────────────────────────────────────

class AuditFinding(_Strict):
    area: Literal["content", "engagement", "audience", "consistency", "profile", "other"]
    observation: str = Field(min_length=1, max_length=500)
    metric_keys: list[str] = Field(default_factory=list, max_length=10)   # which MEASURED fields this is based on
    recommendation: str = Field(min_length=1, max_length=500)
    priority: Literal["high", "medium", "low"] = "medium"


def _short_list(v: list[str]) -> list[str]:
    for item in v:
        if len(item) > 200:
            raise ValueError("each item must be at most 200 characters")
    return [i.strip() for i in v if i.strip()]


class AuditAssessment(_Strict):
    """AI opinion over measured data. Never holds numbers of its own: the measured snapshot is stored separately."""
    summary: str = Field(min_length=1, max_length=1500)
    strengths: list[str] = Field(default_factory=list, max_length=8)
    findings: list[AuditFinding] = Field(default_factory=list, max_length=12)
    stop: list[str] = Field(default_factory=list, max_length=5)
    keep: list[str] = Field(default_factory=list, max_length=5)
    test: list[str] = Field(default_factory=list, max_length=5)
    not_enough_signal: list[str] = Field(default_factory=list, max_length=5)   # questions the data cannot answer yet

    @field_validator("strengths", "stop", "keep", "test", "not_enough_signal")
    @classmethod
    def _lists(cls, v):
        return _short_list(v)


class CalendarEntry(_Strict):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: Literal["post", "carousel", "story", "promo"]
    pillar: str = Field(min_length=1, max_length=60)
    idea: str = Field(min_length=1, max_length=300)


class MarketingPlanBody(_Strict):
    goals: list[str] = Field(min_length=1, max_length=6)
    audience: str = Field(min_length=1, max_length=600)
    pillars: list[str] = Field(min_length=1, max_length=5)              # more than five means no focus
    position: Optional[str] = Field(default=None, max_length=300)       # one sentence: what the account is about
    rotation: Optional[str] = Field(default=None, max_length=300)       # how often each pillar appears in a week
    out_of_scope: list[str] = Field(default_factory=list, max_length=8)  # what the account does not post
    cadence: str = Field(min_length=1, max_length=200)
    calendar: list[CalendarEntry] = Field(default_factory=list, max_length=62)

    @model_validator(mode="after")
    def _pillars_known(self):
        names = {p.strip().lower() for p in self.pillars}
        unknown = sorted({e.pillar for e in self.calendar if e.pillar.strip().lower() not in names})
        if unknown:
            raise ValueError(f"calendar uses pillars that are not in the plan: {', '.join(unknown)[:200]}")
        return self


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
