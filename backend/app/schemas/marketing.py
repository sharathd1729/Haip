"""Marketing Studio schemas (docs/marketing-website/PHASE0_AUDIT.md §7.3).

Every content version, plan and audit assessment is validated against these models before it is stored, whether a
person wrote it or the AI did. Limits follow Instagram's published caps (caption 2,200 characters, 30 hashtags,
carousel 2-10 items, story frames one at a time).
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTENT_KINDS = ("post", "carousel", "story", "promo", "reel")
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


class VoiceTrait(_Strict):
    """One trait of the brand voice, written the way an agency style guide does: what it is and where it stops."""
    trait: str = Field(min_length=1, max_length=40)                  # e.g. "Warm"
    we_are: str = Field(min_length=1, max_length=200)                # "Warm and specific: we name the place and the hour"
    we_are_not: str = Field(min_length=1, max_length=200)            # "Gushing: no 'magical', no exclamation marks"
    sounds_like: Optional[str] = Field(default=None, max_length=200)
    not_like: Optional[str] = Field(default=None, max_length=200)


class ChannelTone(_Strict):
    """The voice stays the same everywhere; the tone shifts by channel."""
    instagram: Optional[str] = Field(default=None, max_length=200)
    whatsapp: Optional[str] = Field(default=None, max_length=200)
    review_replies: Optional[str] = Field(default=None, max_length=200)
    ads: Optional[str] = Field(default=None, max_length=200)


class ApprovedClaim(_Strict):
    """A fact the owner has confirmed may be said in public (agency M2), e.g. "12 km from Madikeri town"."""
    text: str = Field(min_length=3, max_length=200)
    source: Optional[str] = Field(default=None, max_length=200)    # where it comes from: "Google Maps", "award 2025"


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
    voice: list[VoiceTrait] = Field(default_factory=list, max_length=5)
    channel_tone: ChannelTone = Field(default_factory=ChannelTone)   # `tone` above stays the overall "how you sound"
    claims: list[ApprovedClaim] = Field(default_factory=list, max_length=40)
    home_state: Optional[str] = Field(default=None, max_length=40)   # for state holidays; e.g. "KA" or "Karnataka"

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
    # From the brand kit (agency M3), frozen when photos are attached; None = the renderer's plain default.
    accent: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    font: Optional[Literal["plain", "sans", "serif"]] = None
    logo_asset_id: Optional[str] = Field(default=None, max_length=64)
    logo_position: Optional[Literal["top_left", "top_right", "none"]] = None


class BrandKit(_Strict):
    """brand_config.marketing_studio.brand_kit (agency M3). primary = the panel/brand colour, accent = the CTA pill
    and accent bar. plain = the bundled font; sans/serif need the Noto fonts in the image (backend/Dockerfile)."""
    logo_asset_id: Optional[str] = Field(default=None, max_length=64)
    primary: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    font: Literal["plain", "sans", "serif"] = "plain"
    logo_position: Literal["top_left", "top_right", "none"] = "top_right"


class CommentDM(_Strict):
    """"Comment STAY for dates" (agency M3): when someone comments the keyword on this post, Instagram sends them this
    DM (and optionally a short public reply). Part of the approved payload, so the approval covers the DM text too."""
    keyword: str = Field(pattern=r"^[A-Za-z0-9\u0900-\u097f]{2,20}$")
    message: str = Field(min_length=10, max_length=1000)
    public_reply: Optional[str] = Field(default=None, max_length=300)


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
    comment_dm: Optional[CommentDM] = None


class CarouselSlide(_Strict):
    media: MediaRef = Field(default_factory=MediaRef)
    headline: Optional[str] = Field(default=None, max_length=80)
    body: Optional[str] = Field(default=None, max_length=200)


# Carousel structures (adapted from coreyhaines31/marketingskills `social`, MIT; THIRD_PARTY_NOTICES.md):
# list = N reasons/places/things, itinerary = day by day, walkthrough = a tour of the stay, problem_proof = the trip
# people want and why this stay delivers it, guide = how to plan or do something.
CAROUSEL_FRAMEWORKS = ("list", "itinerary", "walkthrough", "problem_proof", "guide")


class CarouselContent(_Captioned):
    kind: Literal["carousel"] = "carousel"
    slides: list[CarouselSlide] = Field(min_length=2, max_length=10)
    design: Optional[Design] = None
    framework: Optional[Literal["list", "itinerary", "walkthrough", "problem_proof", "guide"]] = None
    comment_dm: Optional[CommentDM] = None


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
    comment_dm: Optional[CommentDM] = None


REEL_MAX_SECONDS = 60


class ReelClip(_Strict):
    """One cut of a reel: a library clip (from start_s, for `seconds`) or a still photo shown with a slow zoom."""
    media: MediaRef = Field(default_factory=MediaRef)
    start_s: float = Field(default=0, ge=0, le=600)
    seconds: float = Field(default=3, ge=1, le=15)
    caption: Optional[str] = Field(default=None, max_length=80)      # drawn on the video
    shot_note: Optional[str] = Field(default=None, max_length=200)   # what to film if the library has nothing that fits


class ReelContent(_Captioned):
    """A reel cut from the property's own clips (agency M3; services/marketing_reel.py). No music, no clip sound."""
    kind: Literal["reel"] = "reel"
    clips: list[ReelClip] = Field(min_length=2, max_length=12)
    cover_text: Optional[str] = Field(default=None, max_length=60)
    cover_clip: int = Field(default=0, ge=0)
    design: Optional[Design] = None
    comment_dm: Optional[CommentDM] = None
    # Studio plan phase 4, set by people / the producer, never by the AI (marketing_prompts.content_tool drops them):
    # a trial Reel is shown to non-followers first and graduates if it performs (Instagram trial_params);
    # audio_id = a licensed track from Instagram's trending audio, attached at publishing (unverified API, off by default).
    trial: bool = False
    audio_id: Optional[str] = Field(default=None, max_length=64, pattern=r"^[0-9A-Za-z_-]+$")

    @model_validator(mode="after")
    def _length(self):
        if sum(c.seconds for c in self.clips) > REEL_MAX_SECONDS:
            raise ValueError(f"a reel can be at most {REEL_MAX_SECONDS} seconds")
        if self.cover_clip >= len(self.clips):
            raise ValueError("cover_clip must point at one of the clips")
        return self


CONTENT_MODELS: dict[str, type[BaseModel]] = {
    "post": PostContent, "carousel": CarouselContent, "story": StoryContent, "promo": PromoContent, "reel": ReelContent,
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
                if k not in ("asset_id", "kind", "date", "valid_until", "framework", "style", "colour", "accent", "font",
                             "logo_asset_id", "logo_position"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(payload)
    return parts


def text_of(payload: dict) -> str:
    return "\n".join(strings_of(payload))


# ── Photo tags (services/marketing_vision.py) ────────────────────────────────────────────────────────────────────────

PHOTO_SUBJECTS = ("bedroom", "bathroom", "living_room", "kitchen", "dining", "exterior", "pool", "garden", "view",
                  "food", "drink", "activity", "vehicle", "detail", "amenity", "local_area", "people")


class PhotoTags(_Strict):
    """What a vision model saw in one library photo. Used to pick photos; `people` photos need the owner's OK."""
    subjects: list[Literal["bedroom", "bathroom", "living_room", "kitchen", "dining", "exterior", "pool", "garden",
                           "view", "food", "drink", "activity", "vehicle", "detail", "amenity", "local_area",
                           "people"]] = Field(default_factory=list, max_length=6)
    light: Literal["day", "golden_hour", "night", "indoor", "unknown"] = "unknown"
    season: Literal["monsoon", "winter", "summer", "any"] = "any"
    people: bool = False
    text_or_logo: bool = False
    quality: int = Field(default=3, ge=1, le=5)
    mood: list[str] = Field(default_factory=list, max_length=4)
    description: str = Field(min_length=1, max_length=200)

    @field_validator("mood")
    @classmethod
    def _mood(cls, v):
        return [m.strip().lower()[:20] for m in v if m and m.strip()]


# ── Brand review (services/marketing_review_service.py) ─────────────────────────────────────────────────────────────

class ReviewFinding(_Strict):
    """One issue in a draft. `high` comes only from the deterministic checks and blocks the agency from sending the
    draft for approval; the AI reviewer's findings are advice (medium/low) shown to the approver."""
    rule: str = Field(min_length=1, max_length=40)
    severity: Literal["high", "medium", "low"]
    where: str = Field(min_length=1, max_length=60)              # "caption", "slide 2", "frame 1"
    message: str = Field(min_length=1, max_length=300)
    quote: Optional[str] = Field(default=None, max_length=200)   # the words in the draft it refers to
    suggestion: Optional[str] = Field(default=None, max_length=300)


class AIReviewFinding(_Strict):
    issue: str = Field(min_length=1, max_length=300)
    where: str = Field(min_length=1, max_length=60)
    severity: Literal["medium", "low"]
    quote: Optional[str] = Field(default=None, max_length=200)
    suggestion: Optional[str] = Field(default=None, max_length=300)


class CriticScores(_Strict):
    """The critic's 1-5 marks (agency M3). Below the bar (average < 3.5 or any mark <= 2) the agency rewrites once."""
    hook: int = Field(ge=1, le=5)          # does the first line stop the scroll
    specificity: int = Field(ge=1, le=5)   # concrete details of THIS place, not any resort
    voice: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    ask: int = Field(ge=1, le=5)           # one clear next step


class AIBrandReview(_Strict):
    summary: str = Field(min_length=1, max_length=500)
    findings: list[AIReviewFinding] = Field(default_factory=list, max_length=8)
    scores: Optional[CriticScores] = None


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
    kind: Literal["post", "carousel", "story", "promo", "reel"]
    pillar: str = Field(min_length=1, max_length=60)
    idea: str = Field(min_length=1, max_length=300)
    # Agency M2 (all optional so older plans still validate):
    targets: Optional[str] = Field(default=None, max_length=80)        # the free dates or occasion it sells, e.g. "2026-11-13 to 2026-11-16"
    campaign: Optional[str] = Field(default=None, max_length=80)
    bucket: Optional[Literal["proven", "new", "experimental"]] = None
    indicator: Optional[str] = Field(default=None, max_length=160)     # the early signal to watch
    stop_if: Optional[str] = Field(default=None, max_length=160)       # when to stop doing this


class Campaign(_Strict):
    name: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=200)
    targets: Optional[str] = Field(default=None, max_length=120)       # dates or occasion
    channels: list[str] = Field(default_factory=list, max_length=6)


class MarketingPlanBody(_Strict):
    goals: list[str] = Field(min_length=1, max_length=6)
    audience: str = Field(min_length=1, max_length=600)
    pillars: list[str] = Field(min_length=1, max_length=5)              # more than five means no focus
    position: Optional[str] = Field(default=None, max_length=300)       # one sentence: what the account is about
    rotation: Optional[str] = Field(default=None, max_length=300)       # how often each pillar appears in a week
    out_of_scope: list[str] = Field(default_factory=list, max_length=8)  # what the account does not post
    cadence: str = Field(min_length=1, max_length=200)
    calendar: list[CalendarEntry] = Field(default_factory=list, max_length=62)
    campaigns: list[Campaign] = Field(default_factory=list, max_length=6)
    reactive_days: list[str] = Field(default_factory=list, max_length=12)   # days kept free for what happens that week

    @model_validator(mode="after")
    def _pillars_known(self):
        names = {p.strip().lower() for p in self.pillars}
        unknown = sorted({e.pillar for e in self.calendar if e.pillar.strip().lower() not in names})
        if unknown:
            raise ValueError(f"calendar uses pillars that are not in the plan: {', '.join(unknown)[:200]}")
        return self
