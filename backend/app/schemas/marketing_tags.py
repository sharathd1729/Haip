"""Creative tags (studio plan phase 1): one record per post, Reel or ad, so the insights report can say which ELEMENTS
work. The AI tags from the text HAIP has (caption, slide text, photo descriptions, ad copy); "unknown" whenever that text
does not show it, never a guess. The owner can correct any field (PATCH), and a corrected record is never re-tagged."""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Format = Literal["reel", "carousel", "photo", "story", "video", "unknown"]
LengthBand = Literal["under_7s", "7_15s", "15_30s", "30_60s", "over_60s", "not_video", "unknown"]
HookType = Literal["question", "number", "pov", "offer", "moment", "reveal", "statement", "none", "unknown"]
Persona = Literal["couple", "family", "friends", "solo", "corporate", "pet_owners", "unknown"]
Emotion = Literal["calm", "excitement", "romance", "nostalgia", "fomo", "joy", "awe", "unknown"]
Talent = Literal["none", "couple", "family", "kids", "creator", "staff", "unknown"]
YesNo = Literal["yes", "no", "unknown"]
Cta = Literal["whatsapp", "dm", "link", "call", "book", "comment", "none", "unknown"]
Pacing = Literal["fast", "medium", "slow", "static", "unknown"]
Audio = Literal["trending", "music", "voiceover", "ambient", "none", "unknown"]

# Fields the report groups by, in display order (tag key -> label).
TAG_FIELDS = {"format": "Format", "length_band": "Length", "hook_type": "Hook", "first_frame": "Opening shot",
              "angle": "Angle", "persona": "Persona", "emotion": "Emotion", "destination": "Destination",
              "talent": "Who is in it", "text_overlay": "Text on screen", "cta": "Call to action", "pacing": "Pacing",
              "audio": "Audio", "occasion": "Season / occasion"}


class CreativeTags(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Format = "unknown"
    length_band: LengthBand = "unknown"
    hook_type: HookType = "unknown"
    first_frame: str = Field(default="unknown", max_length=40, description="Main subject of the first image/frame, 1-3 words")
    angle: str = Field(default="unknown", max_length=40, description="The selling angle, 1-3 words, e.g. 'romantic escape'")
    persona: Persona = "unknown"
    emotion: Emotion = "unknown"
    destination: str = Field(default="unknown", max_length=60, description="Place named or shown, else unknown")
    talent: Talent = "unknown"
    text_overlay: YesNo = "unknown"
    cta: Cta = "unknown"
    pacing: Pacing = "unknown"
    audio: Audio = "unknown"
    occasion: str = Field(default="none", max_length=40, description="Season or occasion, e.g. 'diwali', 'monsoon', or none")


class CreativeTagsPatch(BaseModel):
    """Owner correction: any subset of the fields."""
    model_config = ConfigDict(extra="forbid")
    format: Optional[Format] = None
    length_band: Optional[LengthBand] = None
    hook_type: Optional[HookType] = None
    first_frame: Optional[str] = Field(default=None, max_length=40)
    angle: Optional[str] = Field(default=None, max_length=40)
    persona: Optional[Persona] = None
    emotion: Optional[Emotion] = None
    destination: Optional[str] = Field(default=None, max_length=60)
    talent: Optional[Talent] = None
    text_overlay: Optional[YesNo] = None
    cta: Optional[Cta] = None
    pacing: Optional[Pacing] = None
    audio: Optional[Audio] = None
    occasion: Optional[str] = Field(default=None, max_length=40)


def normalise(tags: dict) -> dict:
    """Free-text fields lower-cased and trimmed, so 'Kabini ' and 'kabini' group together."""
    out = dict(tags)
    for k in ("first_frame", "angle", "destination", "occasion"):
        out[k] = (str(out.get(k) or "unknown").strip().lower() or "unknown")[:60]
    return out
