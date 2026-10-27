"""Operations module: staff, shift roster, escalation chains and ops items (docs/ops/OPS_MODULE_PLAN.md §3–§5).

Constants here are the single definition of duties, severities, item kinds and default SLAs; services and endpoints import them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DUTIES = (
    "housekeeping",
    "maintenance",
    "front_desk",
    "caretaker",
    "driver",
    "fnb",
    "ops_manager",
)
SEVERITIES = ("low", "normal", "high", "critical")
ITEM_KINDS = ("incident", "balance_due", "checklist_overdue", "manual")
ITEM_STATUSES = ("open", "acknowledged", "resolved", "cancelled")
OVERRIDE_KINDS = ("leave", "extra", "swap")
INCIDENT_CATEGORIES = (
    "ac",
    "plumbing",
    "power",
    "wifi",
    "housekeeping",
    "amenity_missing",
    "food",
    "safety",
    "noise",
    "vehicle",
    "payment",
    "other",
)

# (ack within, resolve within) in minutes, per severity. Tenants override in ops_settings.sla.
DEFAULT_SLA_MINUTES: dict[str, tuple[int, int]] = {
    "critical": (5, 60),
    "high": (15, 240),
    "normal": (60, 24 * 60),
    "low": (240, 72 * 60),
}

# Escalation chain step types (escalation_chains.steps):
#   {"type": "on_shift"}                    staff on shift for the item's duty at the item's property
#   {"type": "on_shift", "duty": "ops_manager"}   staff on shift for another duty
#   {"type": "duty"}                        anyone holding the item's duty at the property, on shift or not (backup)
#   {"type": "role", "role": "manager"}     HAIP users with that role (owner/manager/...)
#   {"type": "staff", "staff_id": "..."}    one named staff member
STEP_TYPES = ("on_shift", "duty", "role", "staff")
DEFAULT_CHAIN: list[dict] = [
    {"type": "on_shift"},
    {"type": "on_shift", "duty": "ops_manager"},
    {"type": "role", "role": "manager"},
    {"type": "role", "role": "owner"},
]

DEFAULT_TEMPLATES = {"alert": "ops_alert_v1", "escalation": "ops_escalation_v1"}
DEFAULT_QUIET_HOURS = {"start": "22:00", "end": "07:00"}


def _hhmm_to_minute(value: str) -> int:
    h, m = value.split(":")
    minute = int(h) * 60 + int(m)
    if not 0 <= minute <= 1440:
        raise ValueError("time must be between 00:00 and 24:00")
    return minute


# ── Staff ──────────────────────────────────────────────────────────────────


class DutyAssignment(BaseModel):
    duty: str
    property_id: str | None = None  # None = every property

    @field_validator("duty")
    @classmethod
    def _duty(cls, v: str) -> str:
        if v not in DUTIES:
            raise ValueError(f"duty must be one of {DUTIES}")
        return v


class StaffCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    user_id: str | None = None
    languages: list[str] = Field(default_factory=list)
    whatsapp_opt_in: bool = False  # the staff member agreed to receive ops alerts on WhatsApp
    duties: list[DutyAssignment] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=500)


class StaffUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=6, max_length=30)
    user_id: str | None = None
    languages: list[str] | None = None
    whatsapp_opt_in: bool | None = None
    duties: list[DutyAssignment] | None = None
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=500)


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    phone_e164: str
    user_id: str | None = None
    languages: list[str] = Field(default_factory=list)
    whatsapp_opt_in_at: datetime | None = None
    active: bool
    notes: str | None = None
    duties: list[DutyAssignment] = Field(default_factory=list)


# ── Roster ─────────────────────────────────────────────────────────────────


class ShiftPatternCreate(BaseModel):
    staff_id: str
    duty: str
    property_id: str | None = None
    weekdays: list[int] = Field(min_length=1)  # 0 = Monday … 6 = Sunday
    start: str = Field(pattern=r"^\d{2}:\d{2}$")  # local time, workspace timezone
    end: str = Field(pattern=r"^\d{2}:\d{2}$")  # end <= start means the shift crosses midnight

    @field_validator("duty")
    @classmethod
    def _duty(cls, v: str) -> str:
        if v not in DUTIES:
            raise ValueError(f"duty must be one of {DUTIES}")
        return v

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekdays are 0 (Monday) to 6 (Sunday)")
        return sorted(set(v))

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        _hhmm_to_minute(v)
        return v


class ShiftPatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    staff_id: str
    duty: str
    property_id: str | None = None
    weekday: int
    start_minute: int
    end_minute: int
    active: bool


class ShiftOverrideCreate(BaseModel):
    staff_id: str
    kind: str
    starts_at: datetime
    ends_at: datetime
    duty: str | None = None  # required for "extra"
    property_id: str | None = None
    replacement_staff_id: str | None = None  # required for "swap"
    note: str | None = Field(default=None, max_length=300)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in OVERRIDE_KINDS:
            raise ValueError(f"kind must be one of {OVERRIDE_KINDS}")
        return v


class ShiftOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    staff_id: str
    kind: str
    starts_at: datetime
    ends_at: datetime
    duty: str | None = None
    property_id: str | None = None
    replacement_staff_id: str | None = None
    note: str | None = None


class ChainStep(BaseModel):
    type: str
    duty: str | None = None
    role: str | None = None
    staff_id: str | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in STEP_TYPES:
            raise ValueError(f"type must be one of {STEP_TYPES}")
        return v


class EscalationChainPut(BaseModel):
    duty: str
    property_id: str | None = None
    steps: list[ChainStep] = Field(min_length=1, max_length=8)


class OpsSettingsPut(BaseModel):
    alerts_enabled: bool | None = None
    sla: dict[str, list[int]] | None = None  # {"high": [15, 240], ...}
    quiet_hours: dict[str, str] | None = None  # {"start": "22:00", "end": "07:00"}
    templates: dict[str, str] | None = None  # {"alert": "...", "escalation": "..."}
    template_language: str | None = Field(default=None, max_length=10)

    @field_validator("sla")
    @classmethod
    def _sla(cls, v):
        if v is None:
            return v
        for sev, pair in v.items():
            if sev not in SEVERITIES or len(pair) != 2 or pair[0] <= 0 or pair[1] <= 0:
                raise ValueError("sla entries are {severity: [ack_minutes, resolve_minutes]} with positive minutes")
        return v

    @field_validator("quiet_hours")
    @classmethod
    def _quiet(cls, v):
        if v is None:
            return v
        if set(v) != {"start", "end"}:
            raise ValueError("quiet_hours needs start and end")
        for t in v.values():
            _hhmm_to_minute(t)
        return v


# ── Ops items ──────────────────────────────────────────────────────────────


class OpsItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=1000)
    kind: Literal["incident", "manual"] = "incident"
    category: str = "other"
    severity: str = "normal"
    duty: str = "maintenance"
    property_id: str | None = None
    stay_id: str | None = None

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in INCIDENT_CATEGORIES:
            raise ValueError(f"category must be one of {INCIDENT_CATEGORIES}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return v

    @field_validator("duty")
    @classmethod
    def _duty(cls, v: str) -> str:
        if v not in DUTIES:
            raise ValueError(f"duty must be one of {DUTIES}")
        return v


class OpsItemAction(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class OpsItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    title: str
    summary: str | None = None
    category: str | None = None
    severity: str
    duty: str
    status: str
    source: str
    property_id: str | None = None
    stay_id: str | None = None
    current_step: int
    ack_due_at: datetime | None = None
    resolve_due_at: datetime | None = None
    dispatch_after: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by_staff_id: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    escalation_exhausted: bool = False
    created_at: datetime


class OpsEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event: str
    step: int | None = None
    actor_staff_id: str | None = None
    actor_user_id: str | None = None
    detail: dict[str, Any] | None = None
    created_at: datetime


class OpsAlertSendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    step: int
    staff_id: str | None = None
    user_id: str | None = None
    channel: str
    template: str | None = None
    status: str
    error: str | None = None
    created_at: datetime
