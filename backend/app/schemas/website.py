"""Website builder request/response schemas. The page document itself is validated by services/website_blocks.py
against services/website_blocks.json (mirrored in frontend/src/site-blocks/blocks.json)."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

BOOKING_MODES = ("instant", "deposit", "request", "enquiry")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SiteSettings(_Strict):
    """Operational settings: not part of a versioned page document, changed by owner/manager, audited."""
    booking_mode: Literal["instant", "deposit", "request", "enquiry"] = "request"
    deposit_percent: int = Field(30, ge=10, le=100)
    hold_minutes: int = Field(20, ge=16, le=60)            # Razorpay needs a link to live at least 15 minutes
    balance_due_days: int = Field(7, ge=0, le=60)
    show_prices: bool = False
    prices_include_gst: bool = False                       # tariffs in HAIP are pre-tax unless this is set
    property_ids: list[str] = Field(default_factory=list)   # empty = every active, bookable property
    min_nights: int = Field(1, ge=1, le=30)
    max_advance_days: int = Field(365, ge=7, le=730)


class SpecDraftIn(_Strict):
    """A v2 draft from a hand-written SiteSpec (validated by schemas/site_spec.py) or a seeded starter plan."""
    spec: Optional[dict] = None
    seed: Optional[Literal["starter"]] = None

    @model_validator(mode="after")
    def _one(self):
        if (self.seed is None) == (self.spec is None):
            raise ValueError("send either a spec or seed='starter'")
        return self


class SiteCreate(_Strict):
    name: Optional[str] = Field(None, max_length=160)
    slug: Optional[str] = Field(None, max_length=63)


class DraftSave(BaseModel):
    """Autosave of the head draft. base_sha256 is the sha the editor last loaded: a mismatch is a 409, never a merge."""
    doc: dict
    base_sha256: str = Field(min_length=64, max_length=64)


class VersionAction(_Strict):
    version_id: str
    note: Optional[str] = Field(None, max_length=500)


class DomainAdd(_Strict):
    hostname: str = Field(min_length=4, max_length=253)

    @field_validator("hostname")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower().rstrip(".")


class AiRequest(_Strict):
    message: str = Field(min_length=2, max_length=1500)
    page_id: Optional[str] = Field(None, max_length=60)


class AiGenerate(_Strict):
    brief: Optional[str] = Field(None, max_length=1500)


# ─── guest-facing ─────────────────────────────────────────────────────────────────────────────────────────

class QuoteIn(_Strict):
    property_id: str = Field(max_length=64)
    check_in: date
    check_out: date
    adults: int = Field(2, ge=1, le=30)
    children: int = Field(0, ge=0, le=20)
    extras: list[dict] = Field(default_factory=list, max_length=20)   # [{id, quantity}]


class GuestIn(_Strict):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    email: Optional[EmailStr] = None
    note: Optional[str] = Field(None, max_length=1000)
    arrival: Optional[str] = Field(None, max_length=40)
    gstin: Optional[str] = Field(None, max_length=15)
    company: Optional[str] = Field(None, max_length=160)
    nationality: Optional[str] = Field(None, max_length=60)


class ConsentIn(_Strict):
    transactional: bool = True
    marketing: bool = False
    notice_version: str = Field("website-v1", max_length=40)


class HoldIn(_Strict):
    quote: QuoteIn
    guest: GuestIn
    consent: ConsentIn = ConsentIn()
    website: Optional[str] = Field(None, max_length=200)    # honeypot: bots fill every field
    utm: Optional[dict] = None


class EnquiryIn(_Strict):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    email: Optional[EmailStr] = None
    message: Optional[str] = Field(None, max_length=2000)
    property_id: Optional[str] = Field(None, max_length=64)
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    adults: Optional[int] = Field(None, ge=1, le=30)
    consent: ConsentIn = ConsentIn()
    website: Optional[str] = Field(None, max_length=200)
    utm: Optional[dict] = None
    path: Optional[str] = Field(None, max_length=200)


class ManageLookupIn(_Strict):
    ref: str = Field(min_length=4, max_length=20)
    phone: str = Field(min_length=8, max_length=20)


class PageViewIn(_Strict):
    path: str = Field(max_length=200)
    source: Optional[str] = Field(None, max_length=60)


VersionStatus = Literal["draft", "in_review", "approved", "published", "superseded", "rejected", "withdrawn"]
