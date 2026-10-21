"""Partnerships and the reputation loop (agency M7): creators, creator (barter) deals, OTA listing copy, review posts.

ASCI's influencer guidelines (2021, updated for barter/gifted content) require a clear disclosure label on any content
made in return for something of value, including a free stay. HAIP checks that the creator's caption carries one of
the labels below before a deliverable counts as delivered; a person confirms the post itself.
"""
import re
from datetime import date
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from app.schemas.marketing import _Strict

ASCI_LABELS = ("#ad", "#advertisement", "#sponsored", "#collab", "#collaboration", "#partnership", "#gifted",
               "#freegift", "#barter", "paid partnership", "sponsored")
DELIVERABLE_KINDS = ("reel", "post", "story", "video")
OTA_PLATFORMS = ("airbnb", "booking", "makemytrip")
_HANDLE = re.compile(r"^@?[A-Za-z0-9._]{1,30}$")


class CreatorIn(_Strict):
    handle: str = Field(min_length=1, max_length=31)
    name: Optional[str] = Field(default=None, max_length=120)
    platform: Literal["instagram", "youtube"] = "instagram"
    followers: Optional[int] = Field(default=None, ge=0, le=500_000_000)   # as the creator or a person reports it
    niche: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("handle")
    @classmethod
    def _handle(cls, v):
        if not _HANDLE.match(v):
            raise ValueError("a handle is letters, numbers, dots and underscores")
        return v.lstrip("@").lower()


class Deliverable(_Strict):
    kind: Literal["reel", "post", "story", "video"]
    due: Optional[date] = None


class DealIn(_Strict):
    creator_id: str = Field(min_length=1, max_length=64)
    property_id: Optional[str] = Field(default=None, max_length=64)
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    guests: int = Field(default=2, ge=1, le=12)
    comp_value_inr: int = Field(default=0, ge=0, le=10_000_000)     # what the stay would have cost: the deal's cost
    deliverables: list[Deliverable] = Field(default_factory=list, max_length=12)
    notes: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _dates(self):
        if (self.check_in is None) != (self.check_out is None):
            raise ValueError("give both dates or neither")
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValueError("check-out must be after check-in")
        return self


class BookCompIn(_Strict):
    """The creator's contact for the stay. Stored on the guest record (identity_service), not on the creator row."""
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)


class DeliveredIn(_Strict):
    index: int = Field(ge=0, le=11)
    url: str = Field(min_length=10, max_length=500)
    caption: str = Field(min_length=1, max_length=5000)       # pasted by a person; never fetched

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if not v.startswith("https://"):
            raise ValueError("paste the https:// link to the post")
        return v


class ReviewPostIn(_Strict):
    consent_note: str = Field(min_length=5, max_length=300)    # how and when the guest said yes


class OtaCopyIn(_Strict):
    property_id: str = Field(min_length=1, max_length=64)
    platform: Literal["airbnb", "booking", "makemytrip"]


class AirbnbCopy(_Strict):
    title: str = Field(min_length=1, max_length=50)
    summary: str = Field(min_length=1, max_length=500)
    the_space: str = Field(min_length=1, max_length=1500)
    guest_access: Optional[str] = Field(default=None, max_length=500)
    neighbourhood: Optional[str] = Field(default=None, max_length=700)
    getting_around: Optional[str] = Field(default=None, max_length=500)


class BookingCopy(_Strict):
    headline: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    highlights: list[str] = Field(default_factory=list, max_length=8)


class MakeMyTripCopy(_Strict):
    title: str = Field(min_length=1, max_length=80)
    about: str = Field(min_length=1, max_length=2000)
    highlights: list[str] = Field(default_factory=list, max_length=8)
    house_rules: Optional[str] = Field(default=None, max_length=1000)


OTA_MODELS = {"airbnb": AirbnbCopy, "booking": BookingCopy, "makemytrip": MakeMyTripCopy}
