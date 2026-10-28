"""Ops phase 2, readiness and fleet (migration 180): request bodies and the single definitions of paper kinds, defect
severities and the guest form's ID types and consent text."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# kind -> (plain label, critical for a vehicle: expired or expiring before the trip ends blocks dispatch)
PAPER_KINDS: dict[str, tuple[str, bool]] = {
    "insurance": ("Insurance", True),
    "permit": ("Permit", True),
    "fc": ("Fitness certificate (FC)", True),
    "puc": ("Pollution certificate (PUC)", True),
    "ais140": ("AIS-140 tracker certificate", True),
    "hmv_licence": ("HMV driving licence", True),
    "other": ("Other paper", False),
}
VEHICLE_PAPER_KINDS = ("insurance", "permit", "fc", "puc", "ais140", "other")
STAFF_PAPER_KINDS = ("hmv_licence", "other")

ID_TYPES = {
    "aadhaar": "Aadhaar",
    "passport": "Passport",
    "driving_licence": "Driving licence",
    "voter_id": "Voter ID",
    "other": "Other government ID",
}
# A wording change = a new version; the version and the exact text the guest saw are what they agreed to.
CONSENT_VERSION = "ops-guest-form-v1"
CONSENT_TEXT = (
    "I confirm these details are correct for everyone travelling, and I accept the booking terms. The details are kept "
    "private and used only to register this trip and for safety on the road."
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperIn(_Strict):
    property_id: str | None = None
    staff_id: str | None = None
    kind: Literal["insurance", "permit", "fc", "puc", "ais140", "hmv_licence", "other"]
    name: str | None = Field(default=None, max_length=120)  # empty = the kind's label
    number: str | None = Field(default=None, max_length=60)
    expires_on: date | None = None


class DefectIn(_Strict):
    property_id: str
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=2000)
    severity: Literal["critical", "normal"] = "normal"


class DefectCloseIn(_Strict):
    note: str | None = Field(default=None, max_length=1000)


class ServiceIn(_Strict):
    property_id: str
    name: str = Field(min_length=1, max_length=120)
    due_on: date | None = None
    due_km: int | None = Field(default=None, gt=0, lt=10_000_000)
    note: str | None = Field(default=None, max_length=500)


class ServiceDoneIn(_Strict):
    done_km: int | None = Field(default=None, gt=0, lt=10_000_000)
    note: str | None = Field(default=None, max_length=500)


class InventoryIn(_Strict):
    property_id: str
    name: str = Field(min_length=1, max_length=80)
    par: int = Field(ge=0, le=10_000)
    count: int | None = Field(default=None, ge=0, le=10_000)


class InventoryCountIn(_Strict):
    count: int | None = Field(default=None, ge=0, le=10_000)
    par: int | None = Field(default=None, ge=0, le=10_000)


class GuestEntryIn(_Strict):
    name: str = Field(default="", max_length=200)
    age: str = Field(default="", max_length=5)
    id_type: str = Field(default="", max_length=30)
    id_number: str = Field(default="", max_length=60)


class GuestFormIn(_Strict):
    guests: list[GuestEntryIn] = Field(min_length=1, max_length=12)
    emergency_name: str = Field(default="", max_length=200)
    emergency_phone: str = Field(default="", max_length=40)
    food: str = Field(default="", max_length=1000)
    requests: str = Field(default="", max_length=2000)
    signed_name: str = Field(default="", max_length=200)
    agreed: bool = False
    consent_version: str = Field(default="", max_length=40)

    @field_validator("consent_version")
    @classmethod
    def _current(cls, v: str) -> str:
        if v and v != CONSENT_VERSION:
            raise ValueError("The form has changed. Please reload the page.")
        return v
