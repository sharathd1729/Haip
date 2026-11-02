"""Ops files (migration 179): one per booking, walked through its pack's steps. Request bodies and the typed pack details.

The caravan pack's details are what the prototype called the trip: route, stops, km included, extra-km rate, crew, odometer.
Amounts are rupees. ``extra_km_rate`` is per km BEFORE GST unless ``rate_includes_gst`` (published Rathaa data: GST on top).
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EXPENSE_CATEGORIES = (
    "fuel",
    "toll",
    "parking",
    "driver",
    "helper",
    "repair",
    "consumables",
    "groceries",
    "other",
)
EXTRA_KINDS = ("upsell", "extra_hours", "extra_route", "extra_guest", "damage", "other")
ITEM_STATUSES = ("pending", "green", "red")
SETTLE_STEPS = ("return_checked", "report_approved")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaravanDetails(_Strict):
    """Stored in ops_files.details for pack caravan_rv. Every field is optional until the step that needs it."""

    route: str | None = Field(default=None, max_length=200)
    stops: list[str] = Field(default_factory=list, max_length=20)
    allowance_km: Decimal | None = Field(default=None, gt=0)
    extra_km_rate: Decimal | None = Field(default=None, ge=0)
    rate_includes_gst: bool = False
    rate_source: str | None = Field(default=None, max_length=40)  # quote_km | package | manager
    driver_staff_id: str | None = None
    helper_staff_id: str | None = None
    start_odometer: int | None = Field(default=None, gt=0)
    end_odometer: int | None = Field(default=None, gt=0)
    extra_km_addon_id: str | None = None  # the stay_addons row billing the extra distance
    # Start odometer read from the driver's photo before Dispatch: pre-fills the manager's tap, never dispatches by itself.
    start_odometer_photo_km: int | None = Field(default=None, gt=0)
    start_odometer_photo_key: str | None = None
    end_odometer_photo_key: str | None = None


class AcceptIn(_Strict):
    route: str = Field(min_length=1, max_length=200)
    stops: list[str] = Field(default_factory=list, max_length=20)
    allowance_km: Decimal | None = Field(default=None, gt=0)  # empty = take it from the quote
    extra_km_rate: Decimal | None = Field(default=None, ge=0)
    rate_includes_gst: bool | None = None

    @field_validator("stops")
    @classmethod
    def _clean_stops(cls, v: list[str]) -> list[str]:
        return [s.strip()[:80] for s in v if s and s.strip()]


class CrewIn(_Strict):
    driver_staff_id: str
    helper_staff_id: str


class ItemSetIn(_Strict):
    status: Literal["pending", "green", "red"]
    note: str | None = Field(default=None, max_length=500)


class OdometerIn(_Strict):
    reading_km: int = Field(gt=0, lt=10_000_000)


class ExpenseIn(_Strict):
    category: Literal[
        "fuel",
        "toll",
        "parking",
        "driver",
        "helper",
        "repair",
        "consumables",
        "groceries",
        "other",
    ]
    amount: Decimal = Field(gt=0, le=Decimal(10000000))
    gst_amount: Decimal | None = Field(default=None, ge=0)
    vendor: str | None = Field(default=None, max_length=120)
    bill_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str | None = Field(default=None, max_length=300)


class ExtraIn(_Strict):
    kind: Literal["upsell", "extra_hours", "extra_route", "extra_guest", "damage", "other"]
    label: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, le=Decimal(10000000))  # charged to the guest, GST included


class SettleIn(_Strict):
    step: Literal["return_checked", "report_approved"]


# ── Villa pack (phase 4) ────────────────────────────────────────────────────

MEALS = ("breakfast", "lunch", "dinner")
FOOD = ("veg", "non_veg", "mixed")


class Meal(_Strict):
    """One meal the cook makes. Editing a meal clears its confirmation; the cook confirms by WhatsApp reply or a person
    marks it (confirmed_by = "cook" or a user id)."""

    id: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    meal: Literal["breakfast", "lunch", "dinner"]
    guests: int = Field(ge=1, le=60)
    food: Literal["veg", "non_veg", "mixed"] = "veg"
    notes: str | None = Field(default=None, max_length=300)
    sent_at: str | None = None  # when the plan went to the cook on WhatsApp
    confirmed_at: str | None = None
    confirmed_by: str | None = None


class VillaDetails(_Strict):
    """Stored in ops_files.details for pack villa. OpsFile columns are shared with the caravan pack: dispatched_at = the
    guest was welcomed (check-in), returned_at = checked out, return_checked_at = inspection done."""

    caretaker_staff_id: str | None = None
    cook_staff_id: str | None = None
    cleaner_staff_id: str | None = None
    keys_handed: bool = False
    deposit_collected: bool | None = None  # None = not asked yet (before check-in)
    check_in_note: str | None = Field(default=None, max_length=500)
    meals: list[Meal] = Field(default_factory=list, max_length=200)
    deposit_decision: str | None = None  # refund | deduct
    deposit_reason: str | None = Field(default=None, max_length=500)
    deposit_evidence: list[str] = Field(default_factory=list)  # inspection item keys whose photos back the deduction


class PeopleIn(_Strict):
    caretaker_staff_id: str | None = None
    cook_staff_id: str | None = None
    cleaner_staff_id: str | None = None


class CheckInIn(_Strict):
    keys_handed: bool
    deposit_collected: bool
    deposit_amount: Decimal | None = Field(default=None, gt=0, le=Decimal(10000000))  # only when no deposit is on the booking
    note: str | None = Field(default=None, max_length=500)


class MealIn(_Strict):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    meal: Literal["breakfast", "lunch", "dinner"]
    guests: int = Field(ge=1, le=60)
    food: Literal["veg", "non_veg", "mixed"] = "veg"
    notes: str | None = Field(default=None, max_length=300)


class DepositDecisionIn(_Strict):
    decision: Literal["refund", "deduct"]
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal(10000000))  # kept back; deduct only
    reason: str | None = Field(default=None, max_length=500)
