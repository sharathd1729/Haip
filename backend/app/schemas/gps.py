"""Ops GPS (migration 181): request bodies and the ONE dict of alert thresholds.

GPS_RULES is the plan's "Route deviation and live alerts" table. A business may override any number from the GPS settings
page (stored in its gps Integration's config["rules"]); tune them after the first five trips. Severity "high" shows red on
Ops today and alerts the manager at once; "normal" is amber. Night driving is "high" on purpose: quiet hours hold "normal"
alerts until morning, and this rule only fires at night.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GPS_RULES: dict = {
    "off_route_km": 1.5,  # outside the planned road by more than this ...
    "off_route_positions": 3,  # ... for this many positions in a row ...
    "off_route_minutes": 5,  # ... or this long
    "halt_minutes": 30,  # stopped this long ...
    "stop_radius_km": 1.0,  # ... further than this from a planned stop
    "moving_kmh": 5,  # at or above = moving
    "overspeed_kmh": 70,  # RathaOS working top speed
    "overspeed_minutes": 1,
    "night_start": "23:00",  # moving between these local times (unless the route allows night driving)
    "night_end": "05:00",
    "night_minutes": 2,
    "silent_minutes": 15,  # no position this long while the ignition was on
    "severity": {"off_route": "high", "silent": "high", "night": "high", "halt": "normal", "overspeed": "normal"},
}
RULE_KEYS = ("off_route", "halt", "overspeed", "night", "silent")
RETENTION_DAYS = 90


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutePoint(_Strict):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    name: str | None = Field(default=None, max_length=80)
    stop: bool = False  # a planned stop (the first and last points always are)


class RouteIn(_Strict):
    points: list[RoutePoint] = Field(min_length=2, max_length=500)
    night_driving_ok: bool = False


class DetourIn(_Strict):
    reason: str = Field(min_length=2, max_length=300)


class DeviceIn(_Strict):
    external_id: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=120)
    property_id: str | None = None
    active: bool = True

    @field_validator("external_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tracker id is empty.")
        return v


class DevicePatch(_Strict):
    label: str | None = Field(default=None, max_length=120)
    property_id: str | None = None
    active: bool | None = None


class RulesIn(_Strict):
    off_route_km: float | None = Field(default=None, gt=0.2, le=20)
    off_route_positions: int | None = Field(default=None, ge=1, le=20)
    off_route_minutes: int | None = Field(default=None, ge=1, le=60)
    halt_minutes: int | None = Field(default=None, ge=5, le=600)
    stop_radius_km: float | None = Field(default=None, gt=0.1, le=20)
    moving_kmh: float | None = Field(default=None, ge=1, le=30)
    overspeed_kmh: float | None = Field(default=None, ge=20, le=150)
    overspeed_minutes: int | None = Field(default=None, ge=1, le=30)
    night_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    night_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    night_minutes: int | None = Field(default=None, ge=1, le=60)
    silent_minutes: int | None = Field(default=None, ge=5, le=240)


class ConnectionIn(_Strict):
    provider: Literal["webhook", "traccar", "custom_http"]
    base_url: str | None = Field(default=None, max_length=300)
    username: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=500)  # empty = keep the saved one
    rules: RulesIn | None = None
