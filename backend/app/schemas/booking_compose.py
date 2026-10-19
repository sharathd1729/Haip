"""The new-booking flow (/dashboard/bookings/new, POST /bookings/compose). One body for the live preview (partial input is fine:
what is missing comes back as "still needed") and for Create (refused with the same list while anything is missing).

The client sends choices and the prices it typed; the server prices everything with the rate calculator
(services/rate_calculator.py) and only the server's numbers are saved."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.quote_calculator import AddonIn, CustomTripIn

_MONEY = Decimal("10000000")
_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"

# Where a new guest came from -> InquirySource (booking_compose_service.SOURCES). "other" = not recorded.
Source = Literal["instagram", "whatsapp", "phone_call", "meta_ad", "website", "referral", "walk_in", "airbnb", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewGuestIn(_Strict):
    phone: str = Field(min_length=1, max_length=32)
    name: Optional[str] = Field(default=None, max_length=120)
    source: Optional[Source] = None


class OverrideIn(_Strict):
    """"Change the price": the final price in the basis of prices_include_gst. price None = switched on, nothing typed yet."""
    price: Optional[Decimal] = Field(default=None, ge=0, le=_MONEY)
    reason: Optional[str] = Field(default=None, max_length=300)        # team only


class AdvanceIn(_Strict):
    percent: Optional[Decimal] = Field(default=None, ge=0, le=100)     # 25 | 50 | 100
    amount: Optional[Decimal] = Field(default=None, ge=0, le=_MONEY)   # "Other"


class PaymentNowIn(_Strict):
    kind: Literal["none", "paid", "link"] = "none"
    method: Literal["upi", "cash", "bank_transfer", "razorpay"] = "upi"
    amount: Optional[Decimal] = Field(default=None, ge=0, le=_MONEY)   # None = the advance
    reference: Optional[str] = Field(default=None, max_length=120)     # UTR, or the Razorpay pay_ id


class ComposeIn(_Strict):
    # 1 Guest. guest_id = a known person; new_guest = a number typed here (identity_service: an exact phone match reuses the
    # person). inquiry_id = opened from that lead. quote_id = "Start from" a saved quote; start_scratch = "Start from scratch".
    guest_id: Optional[str] = Field(default=None, max_length=64)
    new_guest: Optional[NewGuestIn] = None
    inquiry_id: Optional[str] = Field(default=None, max_length=64)
    quote_id: Optional[str] = Field(default=None, max_length=64)
    start_scratch: bool = False

    # 2 Trip
    mode: Literal["fixed", "custom"] = "fixed"
    package_key: Optional[str] = Field(default=None, max_length=80)
    custom: Optional[CustomTripIn] = None
    check_in: Optional[date] = None
    check_in_time: str = Field(default="12:00", pattern=_HHMM)
    check_out: Optional[date] = None
    check_out_time: str = Field(default="12:00", pattern=_HHMM)
    guests: int = Field(default=2, ge=0, le=50)
    pickup: Optional[str] = Field(default=None, max_length=200)

    # 3 Caravan and interior. property_id None = the first free caravan.
    property_id: Optional[str] = Field(default=None, max_length=64)
    interior: Optional[Literal["Black", "White"]] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    # 4 Add-ons, 5 Price
    addons: list[AddonIn] = Field(default_factory=list, max_length=30)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    gst_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    prices_include_gst: Optional[bool] = None
    override: Optional[OverrideIn] = None

    # 6 Payment
    advance: AdvanceIn = Field(default_factory=lambda: AdvanceIn(percent=Decimal("50")))
    advance_due: Optional[date] = None
    balance_rule: Literal["pickup", "7_days"] = "pickup"
    deposit_amount: Decimal = Field(default=Decimal("0"), ge=0, le=_MONEY)
    deposit_collect: Literal["pickup", "balance"] = "pickup"
    payment: PaymentNowIn = Field(default_factory=PaymentNowIn)

    # 7 Confirmation
    confirmation: Literal["now", "later"] = "now"
    attach_invoice: bool = True
