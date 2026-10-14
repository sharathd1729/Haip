"""Typed shapes of the structured business records (docs/ai/RATHA_KB_EVOLUTION.md §3.1).

Every kind is validated here on every write, so exact commercial values (rates, kilometres, charges, limits, rules) are typed fields
that code can calculate with -- never free text, never something parsed back out of a knowledge-base passage. Money is a Decimal
(stored in JSON as a string); percentages are 0-100.

`extra="forbid"`: an unknown field is an error, not silently ignored, so a typo in a price field cannot be saved as nothing.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

_two_places = AfterValidator(lambda d: d.quantize(Decimal("0.01")))      # stored as "18000.00" however it was typed
Money = Annotated[Decimal, Field(ge=0, le=Decimal("100000000"), decimal_places=2), _two_places]
Percent = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2), _two_places]
HHMM = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$|^[a-z0-9]$")]

KINDS = (
    "package", "destination", "itinerary", "reseller_terms", "discount_policy", "stay_rules", "payment_policy", "cancellation_policy",
)
STATUSES = ("draft", "published", "superseded", "rejected", "inactive")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ─── package ──────────────────────────────────────────────────────────────────────────────────────────────

class Rate(_Strict):
    label: str = Field(min_length=1, max_length=80)
    valid_from: date
    valid_to: date
    amount: Money
    unit: Literal["package", "night", "day"] = "package"
    min_nights: Optional[int] = Field(default=None, ge=0, le=60)
    days_of_week: Optional[list[int]] = None             # 0 = Monday ... 6 = Sunday; None = every day

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, v):
        if v is not None and (not v or any(d < 0 or d > 6 for d in v) or len(set(v)) != len(v)):
            raise ValueError("days_of_week must be unique numbers 0-6")
        return sorted(v) if v else v

    @model_validator(mode="after")
    def _window(self):
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        return self

    def signature(self) -> tuple:
        return (self.unit, self.min_nights or 0, tuple(self.days_of_week or ()))


class ExtraGuestCharge(_Strict):
    free_guests: int = Field(default=0, ge=0, le=50)
    per_guest_per_night: Money


class ExtraKmCharge(_Strict):
    per_km: Money


class Charge(_Strict):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["experience", "driver", "toll", "night_halt", "other"] = "other"
    amount: Money
    unit: Literal["per_stay", "per_night", "per_person", "per_unit"] = "per_stay"
    optional: bool = True


class PackageData(_Strict):
    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1000)
    product: Literal["same_day", "overnight", "multiday", "route"]
    vehicle_property_ids: list[str] = Field(default_factory=list)       # empty = every vehicle
    min_nights: int = Field(default=0, ge=0, le=60)
    max_nights: Optional[int] = Field(default=None, ge=0, le=60)
    max_guests: int = Field(ge=1, le=50)
    included_km: Optional[Decimal] = Field(default=None, ge=0)          # total kilometres included in the package price
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    rates: list[Rate] = Field(min_length=1)
    extra_guest_charge: Optional[ExtraGuestCharge] = None
    extra_km_charge: Optional[ExtraKmCharge] = None
    charges: list[Charge] = Field(default_factory=list)
    destination_keys: list[Slug] = Field(default_factory=list)
    gst_percent: Percent = Decimal("12")
    quote_valid_days: int = Field(default=3, ge=1, le=60)

    @model_validator(mode="after")
    def _consistent(self):
        problems = []
        if self.max_nights is not None and self.max_nights < self.min_nights:
            problems.append("max_nights is below min_nights")
        norm = lambda items: {i.strip().lower() for i in items if i.strip()}
        both = norm(self.inclusions) & norm(self.exclusions)
        if both:
            problems.append(f"listed as both included and excluded: {sorted(both)}")
        if self.gst_percent > 28:
            problems.append("gst_percent above 28")
        rates = self.rates
        for i, a in enumerate(rates):
            for b in rates[i + 1:]:
                if a.signature() == b.signature() and a.valid_from <= b.valid_to and b.valid_from <= a.valid_to:
                    problems.append(f"rates '{a.label}' and '{b.label}' overlap for the same product ({a.valid_from}..{a.valid_to} / {b.valid_from}..{b.valid_to})")
        if self.product == "same_day" and (self.min_nights or 0) > 0:
            problems.append("a same-day package cannot have min_nights above 0")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# ─── destination / itinerary ──────────────────────────────────────────────────────────────────────────────

class Stop(_Strict):
    name: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=1, le=50)
    overnight: bool = False
    distance_km_from_previous: Optional[Decimal] = Field(default=None, ge=0)
    travel_hours_from_previous: Optional[Decimal] = Field(default=None, ge=0)


class DestinationData(_Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    stops: list[Stop] = Field(default_factory=list)
    distance_km_from_base: Decimal = Field(ge=0)
    travel_hours_from_base: Decimal = Field(ge=0)
    best_months: list[int] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _stops(self):
        orders = [s.order for s in self.stops]
        if len(set(orders)) != len(orders):
            raise ValueError("two stops have the same order")
        if any(m < 1 or m > 12 for m in self.best_months):
            raise ValueError("best_months must be 1-12")
        if self.travel_hours_from_base and self.distance_km_from_base and self.distance_km_from_base / self.travel_hours_from_base > 120:
            raise ValueError("distance and travel time imply an average speed above 120 km/h")
        return self


class ItineraryDay(_Strict):
    day: int = Field(ge=1, le=60)
    title: str = Field(min_length=1, max_length=120)
    stops: list[str] = Field(default_factory=list)
    overnight_location: Optional[str] = Field(default=None, max_length=120)
    notes: str = Field(default="", max_length=1000)


class ItineraryData(_Strict):
    name: str = Field(min_length=1, max_length=120)
    destination_key: Slug
    nights: int = Field(ge=0, le=60)
    days: list[ItineraryDay] = Field(min_length=1)
    package_keys: list[Slug] = Field(default_factory=list)

    @model_validator(mode="after")
    def _days(self):
        nums = sorted(d.day for d in self.days)
        if nums != list(range(1, len(nums) + 1)):
            raise ValueError("days must be numbered 1..N without gaps or repeats")
        if len(nums) > self.nights + 1:
            raise ValueError(f"{len(nums)} days do not fit {self.nights} nights")
        return self


# ─── commercial policies ──────────────────────────────────────────────────────────────────────────────────

class ResellerTier(_Strict):
    name: str = Field(min_length=1, max_length=80)
    commission_percent: Percent
    applies_to_package_keys: list[Slug] = Field(default_factory=list)   # empty = all packages
    max_discount_percent: Percent = Decimal("0")


class ResellerTermsData(_Strict):
    tiers: list[ResellerTier] = Field(min_length=1)
    settlement_notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _names(self):
        names = [t.name.lower() for t in self.tiers]
        if len(set(names)) != len(names):
            raise ValueError("two reseller tiers have the same name")
        return self


class DiscountPolicyData(_Strict):
    max_discount_percent: Percent
    max_discount_amount: Optional[Money] = None
    floor_rule: Literal["never_below_base", "none"] = "never_below_base"
    requires_approval_above_percent: Percent = Decimal("0")
    approver_roles: list[Literal["owner", "manager", "reservations"]] = Field(default_factory=lambda: ["owner"])
    valid_conditions: list[str] = Field(default_factory=list)
    stackable: bool = False

    @model_validator(mode="after")
    def _limits(self):
        if self.requires_approval_above_percent > self.max_discount_percent:
            raise ValueError("requires_approval_above_percent is above max_discount_percent")
        return self


class StayRulesData(_Strict):
    check_in_time: HHMM
    check_out_time: HHMM
    early_check_in_allowed: bool = False
    min_age: Optional[int] = Field(default=None, ge=0, le=99)
    id_required: bool = True
    house_rules: list[str] = Field(default_factory=list)


class Instalment(_Strict):
    label: str = Field(min_length=1, max_length=80)
    percent: Percent
    due_days_before_checkin: int = Field(ge=0, le=365)


class PaymentPolicyData(_Strict):
    advance_percent: Percent
    balance_due_days_before_checkin: int = Field(ge=0, le=365)
    instalments: list[Instalment] = Field(default_factory=list)
    accepted_methods: list[Literal["upi", "card", "bank_transfer", "cash", "payment_link"]] = Field(default_factory=lambda: ["payment_link"])
    payment_link_expiry_hours: int = Field(default=48, ge=1, le=720)
    confirmed_by_ratha: bool = False

    @model_validator(mode="after")
    def _sum(self):
        if self.instalments and sum(i.percent for i in self.instalments) != 100:
            raise ValueError("instalment percentages must add up to 100")
        return self


class CancelTier(_Strict):
    days_before: int = Field(ge=0, le=365)
    refund_percent: Percent


class CancellationPolicyData(_Strict):
    tiers: list[CancelTier] = Field(min_length=1)
    non_refundable_items: list[str] = Field(default_factory=list)
    confirmed_by_ratha: bool = False

    @model_validator(mode="after")
    def _monotone(self):
        ordered = sorted(self.tiers, key=lambda t: -t.days_before)
        days = [t.days_before for t in ordered]
        if len(set(days)) != len(days):
            raise ValueError("two cancellation tiers have the same days_before")
        refunds = [t.refund_percent for t in ordered]
        if any(b > a for a, b in zip(refunds, refunds[1:])):
            raise ValueError("the refund must not grow as the stay gets closer")
        return self


KIND_MODELS: dict[str, type[BaseModel]] = {
    "package": PackageData,
    "destination": DestinationData,
    "itinerary": ItineraryData,
    "reseller_terms": ResellerTermsData,
    "discount_policy": DiscountPolicyData,
    "stay_rules": StayRulesData,
    "payment_policy": PaymentPolicyData,
    "cancellation_policy": CancellationPolicyData,
}

# Kinds a guest-facing statement of fact must come from a Ratha-confirmed record (nothing invented).
REQUIRES_CONFIRMATION = ("payment_policy", "cancellation_policy")
# Singletons per tenant: key is fixed.
SINGLETON_KINDS = ("discount_policy", "stay_rules", "payment_policy", "cancellation_policy", "reseller_terms")
SINGLETON_KEY = "default"


def validate_data(kind: str, data: dict) -> tuple[Optional[BaseModel], list[str]]:
    """(parsed model, problems). Problems are plain sentences naming the field."""
    model = KIND_MODELS.get(kind)
    if model is None:
        return None, [f"unknown kind '{kind}'"]
    try:
        return model.model_validate(data), []
    except Exception as exc:                                    # pydantic.ValidationError
        problems = []
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ())) or "(record)"
                msg = str(e.get("msg", "invalid")).removeprefix("Value error, ")
                problems.append(f"{loc}: {msg}")
        else:
            problems.append(str(exc))
        return None, problems


def canonical(model: BaseModel) -> dict:
    """JSON-safe dict of a validated model (Decimals and dates as strings): what is stored."""
    return model.model_dump(mode="json")
