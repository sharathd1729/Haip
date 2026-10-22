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
    level: Optional[str] = Field(default=None, min_length=1, max_length=40)   # e.g. "40000" for an all-inclusive level; the agent picks one
    # The lowest this rate may ever be sold for (a price band: `amount` is the price, `floor_amount` the bottom). A discount that
    # would take the package price below the floor is refused; between the two it still follows the discount policy (approval).
    floor_amount: Optional[Money] = None

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
        if self.floor_amount is not None and self.floor_amount > self.amount:
            raise ValueError("floor_amount is above amount")
        return self

    def signature(self) -> tuple:
        return (self.unit, self.min_nights or 0, tuple(self.days_of_week or ()), self.level or "")


class ExtraGuestCharge(_Strict):
    """Guests above `free_guests`. Older records give `per_guest_per_night`; newer ones give `per_guest` with its `unit`
    (night, billed day, or once for the whole trip). Exactly one of the two amounts is set."""
    free_guests: int = Field(default=0, ge=0, le=50)
    per_guest_per_night: Optional[Money] = None
    per_guest: Optional[Money] = None
    unit: Literal["night", "day", "trip"] = "night"

    @model_validator(mode="after")
    def _one_amount(self):
        if (self.per_guest_per_night is None) == (self.per_guest is None):
            raise ValueError("give exactly one of per_guest_per_night or per_guest")
        if self.per_guest_per_night is not None and self.unit != "night":
            raise ValueError("per_guest_per_night is charged per night; use per_guest with a unit instead")
        return self

    @property
    def amount(self) -> Decimal:
        return self.per_guest if self.per_guest is not None else self.per_guest_per_night


class KmStep(_Strict):
    up_to_extra_km: Optional[Decimal] = Field(default=None, gt=0)    # None = any distance above the previous step
    per_km: Money


class ExtraKmCharge(_Strict):
    """Kilometres above the allowance. Either one fixed `per_km`, or a range the agent picks from (`max_per_km` down to
    `min_per_km`) with an optional `ladder` of suggested rates by extra distance. The applied rate is stored in the quote."""
    per_km: Optional[Money] = None
    max_per_km: Optional[Money] = None
    min_per_km: Optional[Money] = None
    ladder: list[KmStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self):
        ranged = self.max_per_km is not None or self.min_per_km is not None
        if self.per_km is not None and (ranged or self.ladder):
            raise ValueError("give either a fixed per_km or a range (max_per_km / min_per_km), not both")
        if self.per_km is None:
            if self.max_per_km is None or self.min_per_km is None:
                raise ValueError("give a fixed per_km, or both max_per_km and min_per_km")
            if self.min_per_km > self.max_per_km:
                raise ValueError("min_per_km is above max_per_km")
            for st in self.ladder:
                if not (self.min_per_km <= st.per_km <= self.max_per_km):
                    raise ValueError(f"ladder rate {st.per_km} is outside {self.min_per_km}-{self.max_per_km}")
            limits = [st.up_to_extra_km for st in self.ladder]
            if None in limits[:-1] or any(a is not None and b is not None and b <= a for a, b in zip(limits, limits[1:])):
                raise ValueError("ladder steps must go up in distance; only the last step may be open-ended")
        return self

    @property
    def ranged(self) -> bool:
        return self.per_km is None

    def suggested(self, extra_km: Decimal) -> Decimal:
        """The rate to propose for this many extra km: the fixed rate, else the first ladder step that covers it, else the top."""
        if not self.ranged:
            return self.per_km
        for st in self.ladder:
            if st.up_to_extra_km is None or extra_km <= st.up_to_extra_km:
                return st.per_km
        return self.ladder[-1].per_km if self.ladder else self.max_per_km


class ExtraHourCharge(_Strict):
    per_hour: Money


class Charge(_Strict):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["experience", "driver", "toll", "night_halt", "other"] = "other"
    amount: Money
    unit: Literal["per_stay", "per_night", "per_day", "per_person", "per_unit"] = "per_stay"     # per_day = per billed day
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
    # Quote-builder terms (all optional: older records keep these defaults and price exactly as before).
    day_count: Literal["calendar", "noon_to_noon"] = "calendar"         # noon_to_noon: a day is 24 h, billed days = nights (min 1)
    min_days: Optional[int] = Field(default=None, ge=1, le=60)          # fewest billed days
    duration_hours: Optional[int] = Field(default=None, ge=1, le=720)   # a fixed-length package, e.g. 48 (shown on the quote)
    included_km_per_day: Optional[Decimal] = Field(default=None, ge=0)  # kilometres included per billed day
    extra_hour_charge: Optional[ExtraHourCharge] = None                 # none = a late return cannot be quoted
    kits_included: bool = False                                         # experience charges are part of the price (shown at 0)
    at_actuals: list[str] = Field(default_factory=list)                 # e.g. "Tolls and parking": billed at actuals, outside the total
    # The AI sales agent (autopilot) may send this package's quote + payment link without a person first confirming the
    # overnight stay with the partner. Owner's call; off by default.
    auto_bookable: bool = False
    # b2b: a partner / reseller rate. Never listed, matched or quoted to a guest by the AI; staff and partner quotes only.
    audience: Literal["retail", "b2b"] = "retail"

    @model_validator(mode="after")
    def _consistent(self):
        problems = []
        if self.included_km is not None and self.included_km_per_day is not None:
            problems.append("give included_km (whole trip) or included_km_per_day, not both")
        if len({r.level is not None for r in self.rates}) > 1:
            problems.append("either every rate has a level or none does")
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


class Sight(_Strict):
    """An optional place a guest can add to the route, with the kilometres there and back."""
    name: str = Field(min_length=1, max_length=120)
    km_round_trip: Decimal = Field(ge=0, le=5000)


class DestinationData(_Strict):
    """`stops` are the route in order, each with its distance from the previous one (the first from base; the return to base is
    the last stop). A quote's planned km = the sum of those distances + the sights the guest adds."""
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    stops: list[Stop] = Field(default_factory=list)
    sights: list[Sight] = Field(default_factory=list)
    usual_nights: Optional[int] = Field(default=None, ge=0, le=30)
    distance_km_from_base: Decimal = Field(ge=0)
    travel_hours_from_base: Decimal = Field(ge=0)
    best_months: list[int] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)
    auto_bookable: bool = False          # the overnight stays on this route need no partner check before the AI sends a quote

    @model_validator(mode="after")
    def _stops(self):
        orders = [s.order for s in self.stops]
        if len(set(orders)) != len(orders):
            raise ValueError("two stops have the same order")
        names = [x.name.lower() for x in self.sights]
        if len(set(names)) != len(names):
            raise ValueError("two sights have the same name")
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
    # Optional: the agent picks the commission within this range (commission_percent is the default), and the tier's minimums.
    min_commission_percent: Optional[Percent] = None
    max_commission_percent: Optional[Percent] = None
    min_days: Optional[int] = Field(default=None, ge=1, le=60)
    min_billing: Optional[Money] = None                                 # before tax

    @model_validator(mode="after")
    def _range(self):
        lo, hi = self.min_commission_percent, self.max_commission_percent
        if (lo is None) != (hi is None):
            raise ValueError("give both min_commission_percent and max_commission_percent, or neither")
        if lo is not None and not (lo <= self.commission_percent <= hi):
            raise ValueError("commission_percent must lie within min_commission_percent and max_commission_percent")
        return self


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
    # No discount at all below this package price (before tax): small bookings are never discounted.
    min_booking_amount: Optional[Money] = None
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


# Fields added for the quote builder are stored only when used, so a record saved today without them has exactly the shape
# (and the version diffs) it had before they existed.
_OMIT_IF_DEFAULT: dict[type, tuple[str, ...]] = {
    Rate: ("level",),
    ExtraGuestCharge: ("per_guest_per_night", "per_guest", "unit"),
    ExtraKmCharge: ("per_km", "max_per_km", "min_per_km", "ladder"),
    Charge: (),
    PackageData: ("day_count", "min_days", "duration_hours", "included_km_per_day", "extra_hour_charge", "kits_included", "at_actuals",
                  "auto_bookable"),
    DestinationData: ("sights", "usual_nights", "auto_bookable"),
    ResellerTier: ("min_commission_percent", "max_commission_percent", "min_days", "min_billing"),
}


def _prune(model: BaseModel, dumped: dict) -> dict:
    omit = _OMIT_IF_DEFAULT.get(type(model), ())
    for name in list(dumped):
        value = getattr(model, name, None)
        if name in omit and value == type(model).model_fields[name].get_default(call_default_factory=True):
            del dumped[name]
        elif isinstance(value, BaseModel) and isinstance(dumped[name], dict):
            _prune(value, dumped[name])
        elif isinstance(value, list) and isinstance(dumped[name], list):
            for m, d in zip(value, dumped[name]):
                if isinstance(m, BaseModel) and isinstance(d, dict):
                    _prune(m, d)
    return dumped


def canonical(model: BaseModel) -> dict:
    """JSON-safe dict of a validated model (Decimals and dates as strings): what is stored."""
    return _prune(model, model.model_dump(mode="json"))
