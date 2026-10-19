"""Request bodies of the rate calculator (/quote-calculator). The client sends choices and the prices it was shown; the server
recomputes every amount (services/rate_calculator.py) and only the server's numbers are saved or sent."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit = Literal["one_time", "per_day", "per_guest", "per_guest_day"]
LeadSource = Literal["whatsapp", "phone_call", "instagram", "referral", "walk_in", "website", "other"]
_MONEY = Decimal("10000000")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AddonIn(_Strict):
    name: str = Field(min_length=1, max_length=80)
    price: Decimal = Field(ge=0, le=_MONEY)
    unit: Unit = "one_time"


class CustomTripIn(_Strict):
    title: str = Field(default="Custom trip", max_length=120)
    rate_per_day: Decimal = Field(ge=0, le=_MONEY)
    planned_km: Optional[Decimal] = Field(default=None, ge=0, le=20000)
    km_rate: Optional[Decimal] = Field(default=None, ge=0, le=10000)


class OverrideIn(_Strict):
    price: Decimal = Field(gt=0, le=_MONEY)          # in the same basis as prices_include_gst (incl. GST, or before GST)
    reason: Optional[str] = Field(default=None, max_length=300)      # team only, never sent to the guest
    show_usual: bool = True                          # show the usual price struck through (~₹X~) in the message


class CalcIn(_Strict):
    mode: Literal["fixed", "custom"] = "fixed"
    package_key: Optional[str] = Field(default=None, max_length=80)   # "key" or "key::level"
    custom: Optional[CustomTripIn] = None
    start_date: date
    days: int = Field(default=1, ge=1, le=30)
    guests: int = Field(default=1, ge=1, le=50)
    addons: list[AddonIn] = Field(default_factory=list, max_length=30)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    gst_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)   # None = the tenant's default slab
    prices_include_gst: Optional[bool] = None                           # None = the tenant's default
    override: Optional[OverrideIn] = None
    payment_link: bool = True
    inquiry_id: Optional[str] = Field(default=None, max_length=64)      # only to greet the guest by name in the preview

    @model_validator(mode="after")
    def _mode(self):
        if self.mode == "fixed" and not self.package_key:
            raise ValueError("pick a package, or switch to Custom trip")
        if self.mode == "custom" and self.custom is None:
            raise ValueError("a custom trip needs its rate per day")
        return self


class CalcSaveIn(CalcIn):
    """Save to a lead, then send / copy (or only save). `inquiry_id` = an open lead; `guest_id` = a person whose leads are all
    closed (Sold/Lost): a new lead is made for this trip."""
    action: Literal["send", "copy", "save"] = "save"
    guest_id: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _target(self):
        if bool(self.inquiry_id) == bool(self.guest_id):
            raise ValueError("pick the lead (or the person) this quote is for")
        return self


class ShareIn(_Strict):
    action: Literal["send", "copy"]


class NewLeadIn(_Strict):
    phone: str = Field(min_length=6, max_length=32)
    name: Optional[str] = Field(default=None, max_length=120)
    source: LeadSource = "whatsapp"


class QuoteSettingsIn(_Strict):
    gst_percent: Decimal = Field(ge=0, le=100)
    prices_include_gst: bool = True
    advance_percent: Decimal = Field(ge=0, le=100)
    valid_days: int = Field(ge=1, le=60)
    approval_threshold_percent: Decimal = Field(ge=0, le=100)
    max_discount_percent: Decimal = Field(ge=0, le=100)
    greeting: str = Field(default="Namaskara", min_length=1, max_length=40)
