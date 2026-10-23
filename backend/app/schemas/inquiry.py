from datetime import datetime, timezone
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any, Literal

_SLA_DEFAULT_MINUTES = 15


class InquiryOut(BaseModel):
    id: str
    tenant_id: str
    guest_id: str
    property_id: Optional[str] = None
    assigned_to: Optional[str] = None
    stage: str
    source: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_note: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None
    currency: str = "INR"
    quoted_amount: Optional[float] = None
    ai_summary: Optional[str] = None
    ai_next_action: Optional[str] = None
    tags: List[Any] = []
    first_response_at: Optional[datetime] = None

    # K5 — stage age
    current_stage_entered_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    # K6 — SLA state (computed)
    sla_state: Optional[Literal["safe", "warning", "breach"]] = None
    sla_elapsed_seconds: Optional[int] = None

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _compute_sla(self):
        # Only compute for open (non-terminal) stages
        terminal = {"booked", "lost", "ghosted"}
        if self.stage in terminal or self.first_response_at:  # type: ignore[attr-defined]
            return self
        ref = self.current_stage_entered_at or self.created_at
        if not ref:
            return self
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        elapsed = int((datetime.now(timezone.utc) - ref).total_seconds())
        target = _SLA_DEFAULT_MINUTES * 60
        self.sla_elapsed_seconds = elapsed
        if elapsed >= target:
            self.sla_state = "breach"
        elif elapsed >= target // 2:
            self.sla_state = "warning"
        else:
            self.sla_state = "safe"
        return self


class InquiryCreateRequest(BaseModel):
    guest_id: str
    property_id: Optional[str] = None
    source: Optional[str] = "phone"
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None


class InquiryUpdateRequest(BaseModel):
    stage: Optional[str] = None
    # Leads360 restructure Phase 1: preferred over `stage` -- required for
    # tenants that have added a custom pipeline stage. If both are sent,
    # stage_id wins (see inquiries.py PATCH handler).
    stage_id: Optional[str] = None
    # Required when performing a backward stage transition (owner/manager only)
    reason: Optional[str] = None
    property_id: Optional[str] = None
    assigned_to: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_note: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None
    quoted_amount: Optional[float] = None
    # Lead page trip fields (Oct 2026). Empty string clears the field. `pickup` has no column: it is kept in
    # inquiries.custom_fields["pickup"], the Lead Field Registry's place for custom values.
    route_mentioned: Optional[str] = Field(None, max_length=255)
    special_requests: Optional[str] = Field(None, max_length=2000)
    pickup: Optional[str] = Field(None, max_length=255)
    # Migration 171: the guest's starting city (lead_validity's location check). Empty string clears it.
    guest_location: Optional[str] = Field(None, max_length=100)
    # lead_outcome: why the lead was won / lost -- required when a person moves it to a closed-won / closed-lost stage.
    outcome_reason: Optional[str] = Field(None, max_length=30)
    outcome_reason_note: Optional[str] = Field(None, max_length=300)
