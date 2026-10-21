"""Performance marketer (agency M5): ad drafts from approved content, boost rules, ads settings, Conversions API.

Money is whole rupees here; the Meta adapter converts to paise. Every limit is checked twice: by these schemas, and by
marketing_ads_service against the workspace's monthly cap before anything reaches Meta.
"""
from typing import Literal, Optional

from pydantic import Field, model_validator

from app.schemas.marketing import _Strict

DESTINATIONS = ("whatsapp", "instagram")


class Audience(_Strict):
    """People within `radius_km` of a point (Meta custom location), by age."""
    label: str = Field(default="", max_length=80)                 # what the owner calls it, e.g. "Bengaluru"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: int = Field(default=40, ge=1, le=80)
    age_min: int = Field(default=21, ge=18, le=65)
    age_max: int = Field(default=55, ge=18, le=65)

    @model_validator(mode="after")
    def _ages(self):
        if self.age_min > self.age_max:
            raise ValueError("age_min must not be above age_max")
        return self


class AdSettings(_Strict):
    """brand_config.marketing_studio.ads. monthly_cap_inr = 0 means HAIP never spends (the default)."""
    monthly_cap_inr: int = Field(default=0, ge=0, le=10_000_000)
    destination: Literal["whatsapp", "instagram"] = "whatsapp"
    audience: Optional[Audience] = None
    capi_enabled: bool = False                                    # send bookings to Meta as Purchase events
    dataset_id: Optional[str] = Field(default=None, pattern=r"^\d{5,20}$")
    capi_test_code: Optional[str] = Field(default=None, max_length=40)   # Meta's test-events code while trying it


class AdDraftIn(_Strict):
    content_id: str = Field(min_length=1, max_length=64)
    daily_budget_inr: int = Field(ge=100, le=100_000)
    days: int = Field(ge=1, le=30)
    destination: Optional[Literal["whatsapp", "instagram"]] = None
    audience: Optional[Audience] = None


class BoostCondition(_Strict):
    """A weekend (Fri + Sat nights) or a long weekend that is under `occupancy_below_pct` booked once it is
    `days_ahead` days away or closer."""
    window: Literal["weekend", "long_weekend"] = "weekend"
    days_ahead: int = Field(default=10, ge=2, le=60)
    occupancy_below_pct: int = Field(default=50, ge=1, le=100)


class BoostAction(_Strict):
    content: Literal["latest_reel", "latest_post", "specific"] = "latest_reel"
    content_id: Optional[str] = Field(default=None, max_length=64)
    destination: Optional[Literal["whatsapp", "instagram"]] = None
    daily_budget_inr: int = Field(ge=100, le=100_000)
    days: int = Field(default=3, ge=1, le=14)
    max_total_inr: int = Field(ge=100, le=1_000_000)

    @model_validator(mode="after")
    def _caps(self):
        if self.content == "specific" and not self.content_id:
            raise ValueError("choose the post to boost")
        if self.max_total_inr < self.daily_budget_inr:
            raise ValueError("the total cap must be at least one day's budget")
        return self


class BoostRuleIn(_Strict):
    name: str = Field(min_length=1, max_length=80)
    condition: BoostCondition
    action: BoostAction
