"""
Leads360 — Pydantic request/response schemas.

Design notes:
- `budget_estimate` aliases `inquiries.budget` (no DB change)
- `group_type` aliases `inquiries.intent_tag` (no DB change)
- `primary_channel` is derived from `inquiries.source` in the service layer
- `profile_completeness_pct` is computed on read, never stored
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ─── Sub-schemas ──────────────────────────────────────────────────────────────

class PipelineStageMetaSchema(BaseModel):
    count: int = 0
    potential_revenue: float = 0.0


class TimelineEntrySchema(BaseModel):
    id: str
    channel: str          # whatsapp | instagram | call | system
    direction: str        # inbound | outbound | system
    occurred_at: datetime
    content_preview: str  # ≤ 120 chars
    full_content: Optional[str] = None
    is_ai_generated: bool = False
    call_summary: Optional[str] = None      # populated for call entries
    agent_name: Optional[str] = None


class QuoteHistorySchema(BaseModel):
    id: str
    amount: float
    currency: str = "INR"
    created_at: Optional[datetime] = None
    is_active: bool = False
    age_days: Optional[int] = None


# ─── Lead Card ────────────────────────────────────────────────────────────────

class LeadCardSchema(BaseModel):
    # Core identity
    inquiry_id: str
    guest_id: str
    display_name: str           # guest name or "Unknown Guest"
    profile_completeness_pct: int = 0
    identity_signals: List[str] = []   # ["instagram_user_id", "whatsapp_number", ...]

    # Source + channel
    source: Optional[str] = None       # raw InquirySource value
    primary_channel: Optional[str] = None  # derived icon key

    # Stage
    inquiry_stage: str                 # new | responding | quoted | ...
    sla_breached: bool = False

    # Trip intent
    occasion: Optional[str] = None
    group_type: Optional[str] = None   # alias for intent_tag
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None

    # Budget
    budget_estimate: Optional[float] = None   # alias for inquiries.budget
    budget_currency: str = "INR"
    budget_range_label: Optional[str] = None  # formatted from budget_signal if available

    # Quote
    quoted_amount: Optional[float] = None
    quoted_at: Optional[str] = None

    # Properties expressed interest in
    property_interest: List[str] = []  # up to 3 property names from calls.ai_score

    # AI summary (async-generated, may be null)
    ai_summary: Optional[str] = None        # null → show "Generating..." in UI
    ai_next_action: Optional[str] = None

    # Agent + timing
    assigned_agent_name: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    last_touch_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ─── Lead Detail (card + timeline) ───────────────────────────────────────────

class LeadDetailSchema(LeadCardSchema):
    timeline: List[TimelineEntrySchema] = []
    timeline_capped: bool = False
    timeline_total_available: int = 0
    quote_history: List[QuoteHistorySchema] = []
    # Leads360 restructure Phase 3: tenant-configurable field catalog,
    # rendered in display_order alongside/instead of the fixed columns above.
    custom_field_values: List[dict] = []


# ─── List Response ────────────────────────────────────────────────────────────

class LeadsListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    stages: dict[str, PipelineStageMetaSchema] = {}  # stage_value → meta
    leads: List[LeadCardSchema] = []


# ─── Signal Management ────────────────────────────────────────────────────────

class AddSignalRequest(BaseModel):
    type: str   # IdentityType value: phone | whatsapp_number | email | ...
    value: str  # raw value — service normalises


class AddSignalResponse(BaseModel):
    profile_completeness_pct: int
    identity_signals: List[str]
    confidence: float
    merged: bool = False   # True if adding signal triggered an auto-merge


# ─── Refresh Summary ─────────────────────────────────────────────────────────

class RefreshSummaryResponse(BaseModel):
    queued: bool = True
    inquiry_id: str


# ─── Manual Merge ─────────────────────────────────────────────────────────────

class ManualMergeRequest(BaseModel):
    merge_with_inquiry_id: str = Field(
        ..., description="The other inquiry_id to merge into this one"
    )


class ManualMergeResponse(BaseModel):
    merged: bool = True
    survivor_inquiry_id: str
    deprecated_inquiry_id: str
