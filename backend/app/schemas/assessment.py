"""Property assessment + ROI tool: the visitor's answers and the benchmark set the numbers come from.

``AssessmentInput`` is what an anonymous visitor sends, so every number is bounded. Amenity / experience / seasonality
keys are checked against the ACTIVE benchmark set by the engine (they are data, not code).

``BenchmarkSet`` validates a benchmark version before it can be stored (``POST /roi-benchmarks``): every key the engine
reads must exist and every multiplier stays inside a sane range, so an edit can never make the engine crash or print
nonsense. The seed is ``app/data/roi_benchmarks/ka-2026-10-sample-v1.json`` (SAMPLE values, owner to confirm).
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

PropertyType = Literal["hotel", "urban_retreat", "rural_retreat", "farmhouse", "event_space"]
PROPERTY_TYPES = ("hotel", "urban_retreat", "rural_retreat", "farmhouse", "event_space")
SEGMENTS = ("small", "medium", "large")
SQFT_PER_ACRE = 43560
_KEY = r"^[a-z][a-z0-9_]{0,39}$"


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    plot_size: float = Field(gt=0, le=10_000_000)
    plot_unit: Literal["sqft", "acres"] = "sqft"
    rooms: int = Field(ge=0, le=300)                       # keys / units; 0 only for an event space
    property_type: PropertyType
    amenities: list[str] = Field(default_factory=list, max_length=20)
    experiences: list[str] = Field(default_factory=list, max_length=20)
    city: str = Field(min_length=2, max_length=80)
    district: Optional[str] = Field(None, max_length=80)
    landmark: Literal["highway", "airport", "tourist_spot"] = "tourist_spot"
    landmark_km: float = Field(ge=0, le=500)
    seasonality: str = Field("even", pattern=_KEY)
    competitor_density: Literal["low", "medium", "high"] = "medium"
    build_status: Literal["new", "conversion"] = "new"

    @model_validator(mode="after")
    def _plot_and_rooms(self):
        sqft = self.plot_sqft
        if sqft < 500:
            raise ValueError("The plot must be at least 500 sq ft.")
        if sqft > 2000 * SQFT_PER_ACRE:
            raise ValueError("The plot can be at most 2,000 acres.")
        if self.property_type != "event_space" and self.rooms < 1:
            raise ValueError("Enter at least one room or unit.")
        for name in ("amenities", "experiences"):
            items = getattr(self, name)
            if len(set(items)) != len(items) or any(len(i) > 40 for i in items):
                raise ValueError(f"{name.capitalize()} must be distinct, short keys.")
        return self

    @property
    def plot_sqft(self) -> float:
        return self.plot_size * SQFT_PER_ACRE if self.plot_unit == "acres" else self.plot_size


# ── Benchmark set (versioned business config) ────────────────────────────────

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PerSegment(_Strict):
    small: float = Field(ge=0, le=10_000_000)
    medium: float = Field(ge=0, le=10_000_000)
    large: float = Field(ge=0, le=10_000_000)


class EventBench(_Strict):
    per_month: PerSegment
    price_per_event: PerSegment
    venue_sqft: PerSegment


class TypeBench(_Strict):
    label: str = Field(max_length=60)
    adr: PerSegment
    base_occupancy: float = Field(gt=0, le=1)
    build_cost_per_sqft: float = Field(ge=0, le=50_000)
    fitout_per_key: float = Field(ge=0, le=10_000_000)
    running_cost_pct: float = Field(ge=0, le=0.95)
    ota_share: float = Field(ge=0, le=1)
    floors: int = Field(ge=1, le=20)
    built_up_sqft_per_key: float = Field(ge=100, le=5_000)
    common_pct: float = Field(ge=0, le=2)
    parking_sqft_per_key: float = Field(ge=0, le=1_000)
    events: Optional[EventBench] = None
    note: str = Field(max_length=120)


class Multipliers(_Strict):
    adr_mult: float = Field(ge=0.3, le=3.0)
    occ_mult: float = Field(ge=0.3, le=3.0)


class LocationTier(Multipliers):
    label: str = Field(max_length=60)
    places: list[str] = Field(max_length=200)
    note: str = Field(max_length=120)


class Band(Multipliers):
    max_km: Optional[float] = Field(None, ge=0, le=1000)   # None = beyond the last band


class LandmarkBench(_Strict):
    label: str = Field(max_length=60)
    bands: list[Band] = Field(min_length=1, max_length=10)
    note: str = Field(max_length=120)

    @model_validator(mode="after")
    def _ordered(self):
        kms = [b.max_km for b in self.bands]
        if kms[-1] is not None or any(k is None for k in kms[:-1]) or kms[:-1] != sorted(kms[:-1]):
            raise ValueError("Distance bands must be in increasing order and end with an open band (max_km null).")
        return self


class DensityBench(Multipliers):
    label: str = Field(max_length=60)
    note: str = Field(max_length=120)


class SeasonBench(_Strict):
    label: str = Field(max_length=80)
    weights: list[float] = Field(min_length=12, max_length=12)
    note: str = Field(max_length=120)

    @model_validator(mode="after")
    def _positive(self):
        if any(w <= 0 or w > 3 for w in self.weights):
            raise ValueError("Season weights must be between 0 and 3.")
        return self


class AmenityBench(_Strict):
    label: str = Field(max_length=60)
    adr_uplift: float = Field(ge=0, le=0.5)
    capex: float = Field(ge=0, le=100_000_000)
    footprint_sqft: float = Field(ge=0, le=100_000)
    fnb_per_occupied_room_night: Optional[float] = Field(None, ge=0, le=20_000)
    events_per_month: Optional[float] = Field(None, ge=0, le=60)
    price_per_event: Optional[float] = Field(None, ge=0, le=10_000_000)
    note: str = Field(max_length=120)


class ExperienceBench(_Strict):
    label: str = Field(max_length=60)
    revenue_per_occupied_room_night: float = Field(ge=0, le=20_000)
    note: str = Field(max_length=120)


class Scenarios(_Strict):
    low: Multipliers
    likely: Multipliers
    high: Multipliers
    note: str = Field(max_length=120)

    @model_validator(mode="after")
    def _monotonic(self):
        for f in ("adr_mult", "occ_mult"):
            if not getattr(self.low, f) <= getattr(self.likely, f) <= getattr(self.high, f):
                raise ValueError("Scenarios must satisfy low <= likely <= high.")
        return self


class Limits(_Strict):
    occupancy_cap: float = Field(gt=0, le=1)
    occupancy_floor: float = Field(ge=0, lt=1)
    amenity_uplift_cap: float = Field(ge=0, le=1)
    experience_revenue_cap: float = Field(ge=0, le=50_000)
    green_min_pct: float = Field(ge=0, le=0.9)
    note: str = Field(max_length=120)


class Costs(_Strict):
    ota_commission_pct: float = Field(ge=0, le=0.5)
    conversion_build_factor: float = Field(ge=0, le=1.5)
    contingency_pct: float = Field(ge=0, le=0.5)
    note: str = Field(max_length=120)


class Offer(_Strict):
    title: str = Field(max_length=60)
    text: str = Field(max_length=400)
    price_text: str = Field(max_length=160)


class Cta(_Strict):
    saas: Offer
    service: Offer
    note: str = Field(max_length=120)


class Segments(_Strict):
    small_max_sqft: float = Field(gt=0)
    medium_max_sqft: float = Field(gt=0)


class BenchmarkSet(_Strict):
    version: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(max_length=120)
    region: str = Field(max_length=60)
    sample: bool
    note: str = Field(max_length=120)
    segments: Segments
    property_types: dict[str, TypeBench]
    location_tiers: dict[str, LocationTier]
    landmarks: dict[str, LandmarkBench]
    competitor_density: dict[str, DensityBench]
    seasonality: dict[str, SeasonBench]
    amenities: dict[str, AmenityBench]
    experiences: dict[str, ExperienceBench]
    scenarios: Scenarios
    limits: Limits
    costs: Costs
    cta: Cta

    @model_validator(mode="after")
    def _complete(self):
        missing = [t for t in PROPERTY_TYPES if t not in self.property_types]
        if missing:
            raise ValueError(f"Missing property types: {missing}")
        if self.property_types["event_space"].events is None:
            raise ValueError("event_space needs its events block.")
        for need, have in ((("highway", "airport", "tourist_spot"), self.landmarks),
                           (("low", "medium", "high"), self.competitor_density),
                           (("other",), self.location_tiers), (("even",), self.seasonality)):
            absent = [k for k in need if k not in have]
            if absent:
                raise ValueError(f"Missing keys: {absent}")
        if not self.segments.small_max_sqft < self.segments.medium_max_sqft:
            raise ValueError("small_max_sqft must be below medium_max_sqft.")
        if self.limits.occupancy_floor >= self.limits.occupancy_cap:
            raise ValueError("occupancy_floor must be below occupancy_cap.")
        return self


class BenchmarkCreate(_Strict):
    data: BenchmarkSet
    notes: Optional[str] = Field(None, max_length=500)
