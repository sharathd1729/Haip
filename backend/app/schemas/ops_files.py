"""Ops files (migration 179): one per booking, walked through its pack's steps. Request bodies and the typed pack details.

The caravan pack's details are what the prototype called the trip: route, stops, km included, extra-km rate, crew, odometer.
Amounts are rupees. ``extra_km_rate`` is per km BEFORE GST unless ``rate_includes_gst`` (published Rathaa data: GST on top).
"""
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EXPENSE_CATEGORIES = ("fuel", "toll", "parking", "driver", "helper", "repair", "consumables", "groceries", "other")
EXTRA_KINDS = ("upsell", "extra_hours", "extra_route", "extra_guest", "damage", "other")
ITEM_STATUSES = ("pending", "green", "red")
SETTLE_STEPS = ("return_checked", "report_approved")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaravanDetails(_Strict):
    """Stored in ops_files.details for pack caravan_rv. Every field is optional until the step that needs it."""
    route: Optional[str] = Field(default=None, max_length=200)
    stops: list[str] = Field(default_factory=list, max_length=20)
    allowance_km: Optional[Decimal] = Field(default=None, gt=0)
    extra_km_rate: Optional[Decimal] = Field(default=None, ge=0)
    rate_includes_gst: bool = False
    rate_source: Optional[str] = Field(default=None, max_length=40)     # quote_km | package | manager
    driver_staff_id: Optional[str] = None
    helper_staff_id: Optional[str] = None
    start_odometer: Optional[int] = Field(default=None, gt=0)
    end_odometer: Optional[int] = Field(default=None, gt=0)
    extra_km_addon_id: Optional[str] = None                            # the stay_addons row billing the extra distance


class AcceptIn(_Strict):
    route: str = Field(min_length=1, max_length=200)
    stops: list[str] = Field(default_factory=list, max_length=20)
    allowance_km: Optional[Decimal] = Field(default=None, gt=0)          # empty = take it from the quote
    extra_km_rate: Optional[Decimal] = Field(default=None, ge=0)
    rate_includes_gst: Optional[bool] = None

    @field_validator("stops")
    @classmethod
    def _clean_stops(cls, v: list[str]) -> list[str]:
        return [s.strip()[:80] for s in v if s and s.strip()]


class CrewIn(_Strict):
    driver_staff_id: str
    helper_staff_id: str


class ItemSetIn(_Strict):
    status: Literal["pending", "green", "red"]
    note: Optional[str] = Field(default=None, max_length=500)


class OdometerIn(_Strict):
    reading_km: int = Field(gt=0, lt=10_000_000)


class ExpenseIn(_Strict):
    category: Literal["fuel", "toll", "parking", "driver", "helper", "repair", "consumables", "groceries", "other"]
    amount: Decimal = Field(gt=0, le=Decimal("10000000"))
    gst_amount: Optional[Decimal] = Field(default=None, ge=0)
    vendor: Optional[str] = Field(default=None, max_length=120)
    bill_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: Optional[str] = Field(default=None, max_length=300)


class ExtraIn(_Strict):
    kind: Literal["upsell", "extra_hours", "extra_route", "extra_guest", "damage", "other"]
    label: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, le=Decimal("10000000"))               # charged to the guest, GST included


class SettleIn(_Strict):
    step: Literal["return_checked", "report_approved"]
