"""Request bodies of the quote builder (/quotes). Prices are never sent by the client: it sends choices, the server prices them
from published business records (package_pricing_service) and returns the lines."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

StayCheck = Literal["not_checked", "checking", "confirmed"]


class QuoteOptionIn(BaseModel):
    """One option of a quote: a plan, a route, dates and party, and the agent's choices within the published terms."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    package_key: str = Field(min_length=1, max_length=60)
    start_date: date
    nights: int = Field(ge=0, le=30)
    adults: int = Field(ge=1, le=50)
    children: int = Field(default=0, ge=0, le=50)
    level: Optional[str] = Field(default=None, max_length=40)
    destination_key: Optional[str] = Field(default=None, max_length=60)
    sights: list[str] = Field(default_factory=list, max_length=40)
    km_rate: Optional[Decimal] = Field(default=None, ge=0, le=10000)          # applied extra-km rate (within the published range)
    planned_km: Optional[Decimal] = Field(default=None, ge=0, le=20000)       # only to override the route's own distance
    extra_hours: int = Field(default=0, ge=0, le=24)
    kits: list[str] = Field(default_factory=list, max_length=20)              # experience charges by name
    discount_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    vehicle_property_id: Optional[str] = Field(default=None, max_length=64)
    channel: Literal["direct", "reseller"] = "direct"
    reseller_tier: Optional[str] = Field(default=None, max_length=80)
    commission_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)


class QuotePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: QuoteOptionIn
    fallback: Optional[QuoteOptionIn] = None
    stay_check: StayCheck = "not_checked"                                     # the overnight stay: sending needs "confirmed"
    stay_name: Optional[str] = Field(default=None, max_length=120)


class QuoteIssueIn(QuotePreviewIn):
    inquiry_id: str = Field(min_length=1, max_length=64)
    next_step_at: Optional[datetime] = None                                   # becomes (or moves) the lead's follow-up task
    note: Optional[str] = Field(default=None, max_length=1000)
