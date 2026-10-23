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
    # Call entries only — lets the profile render calls as a summary card
    # (duration + QA) instead of a chat bubble.
    call_duration_seconds: Optional[int] = None
    call_qa_score: Optional[float] = None
    call_has_transcript: bool = False
    call_next_action: Optional[str] = None
    call_disposition: Optional[str] = None
    call_occasion: Optional[str] = None
    call_budget_signal: Optional[str] = None
    call_decision_stage: Optional[str] = None
    call_competitor_mentioned: Optional[str] = None
    call_conversion_probability: Optional[int] = None
    call_lost_reason: Optional[str] = None


class QuoteHistorySchema(BaseModel):
    id: str
    amount: float
    currency: str = "INR"
    created_at: Optional[datetime] = None
    is_active: bool = False
    age_days: Optional[int] = None
    status: Optional[str] = None             # issued | superseded | accepted | withdrawn ...
    option_rank: int = 1
    payment_link_status: Optional[str] = None   # created | paid | expired | cancelled (newest link of this option)
    payment_link_url: Optional[str] = None
    booking_id: Optional[str] = None            # the booking a paid link became
    shared_via: Optional[str] = None            # rate calculator: sent | copied (None = saved only)
    valid_until: Optional[datetime] = None
    label: Optional[str] = None                 # the package / trip name


# ─── Lead Card ────────────────────────────────────────────────────────────────

class PendingDraftSchema(BaseModel):
    message_id: str
    conversation_id: str
    preview: str


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
    inquiry_stage: str                 # legacy InquiryStage enum value -- kept for
                                        # the inquiry detail page's cosmetic display,
                                        # not for board column grouping (see stage_key)
    stage_key: Optional[str] = None    # tenant's pipeline_stages.key, or None if unset
    # True while the guest waits past the work queue's "reply" SLA (work_queue_service.SLA_MINUTES); computed on read
    # from the response time below (leads_service._sla_breached), not the dead inquiries.sla_breached column.
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
    # Structured analysis from the same worker (prompt v2): {intent,
    # sentiment, objection, reply_urgency, next_action}. Null for leads
    # whose summary hasn't regenerated since the v2 prompt shipped.
    ai_analysis: Optional[dict] = None

    # Agent + timing
    assigned_agent_name: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    # Round 2 avatar-photos plan: presigned, from the already-loaded
    # assigned_user relationship -- no extra query, generate_presigned_url
    # is a local HMAC signature, not a network call.
    assigned_agent_avatar_url: Optional[str] = None
    last_touch_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    # Response time — computed on read from messages, never stored (same
    # pattern as profile_completeness_pct). The stored first_response_at /
    # sla_breached columns are dead: nothing writes them (sla_breached above is computed from this).
    # status: "waiting" (guest's latest message unanswered; seconds = wait so
    # far) | "responded" (seconds = inbound→reply gap) | None (no messages).
    # Across multiple conversations, any waiting thread beats a responded
    # one, and the longest wait wins.
    response_time_seconds: Optional[int] = None
    response_time_status: Optional[str] = None

    # M5+ WS3: the most recent pending AI-drafted reply for this lead, if
    # any (a Message with is_ai_generated=True, was_approved=None), so the
    # card can offer a one-click "send" without a second round-trip.
    pending_draft: Optional[PendingDraftSchema] = None

    # Auto-send soft-escalation plan: true when the AI's most recent reply
    # on this lead was auto-sent (not held for approval) but the model
    # itself judged the outcome needs a human's personal follow-up -- e.g.
    # a complex custom quote or a frustrated guest. Distinct from
    # pending_draft above, which is a draft still awaiting approval; this
    # reply already went out, the lead just needs a human's attention next.
    needs_agent_followup: bool = False
    needs_agent_followup_reason: Optional[str] = None

    # Lead autopilot: set when the lead's current stage was set by the autopilot (applied, not undone) --
    # {event_id, to_stage_label, reason, source, lost_reason, at}. Drives the list badge.
    autopilot_move: Optional[dict] = None

    # Rate calculator: the lead's newest quote -- {quote_id, amount, status, shared_via, how, valid_until, valid_until_text, label}.
    latest_quote: Optional[dict] = None

    # CRM reporting (migration 169; lead_list_extras): guest | b2b | partner; paid | organic | unknown (lead_paid, derived);
    # a PERSON's "Valid enquiry?" review {status, dates_confirmed, budget_fits, clear_intent, note, by_id, by_name, at}.
    lead_type: str = "guest"
    came_from: Optional[str] = None
    validation: Optional[dict] = None
    # Migration 171 (lead_validity): {enabled, auto_valid, reasons, notes, location, location_field, status, source} -- the
    # automatic rule's answer and the EFFECTIVE validity (a person's review first, B2B/partner never valid).
    validity: Optional[dict] = None
    guest_location: Optional[str] = None


# ─── Lead Detail (card + timeline) ───────────────────────────────────────────

class LeadDetailSchema(LeadCardSchema):
    timeline: List[TimelineEntrySchema] = []
    timeline_capped: bool = False
    timeline_total_available: int = 0
    quote_history: List[QuoteHistorySchema] = []
    # Leads360 restructure Phase 3: tenant-configurable field catalog,
    # rendered in display_order alongside/instead of the fixed columns above.
    custom_field_values: List[dict] = []
    # "Autopilot" pass (Ratha, Sep 2026): a suggested stage move/Mark Lost,
    # in the same RecommendedAction[] shape next_action_service.get_call_actions
    # already uses on the call detail page -- see lead_recommendation_service.py.
    # Human clicks "Apply"; nothing here moves the pipeline on its own.
    recommended_actions: List[dict] = []
    # Lead autopilot (lead_autopilot_view.lead_block): {mode, pinned, pinned_at, last_move, suggestion, history}.
    autopilot: Optional[dict] = None


# ─── List Response ────────────────────────────────────────────────────────────

class LeadsListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    stages: dict[str, PipelineStageMetaSchema] = {}  # stage_value → meta
    leads: List[LeadCardSchema] = []
    # Whose leads these are: "team" (owner/manager) or "mine_and_unassigned" (every other role). The page says so.
    scope: str = "team"


# ─── Needs action (Leads default view) ────────────────────────────────────────

class NeedsActionBucket(BaseModel):
    """One "what to do next" group. A lead appears in exactly one bucket --
    the most urgent that applies (see leads_service.get_needs_action)."""
    key: str                      # draft_ready | waiting | call | followup
    total: int                    # leads in this bucket (may exceed len(leads))
    leads: List[LeadCardSchema] = []


class NeedsActionKpis(BaseModel):
    waiting: int = 0
    waiting_oldest_seconds: Optional[int] = None
    drafts_ready: int = 0
    phone_not_called: int = 0
    unassigned_recent: int = 0    # created in the last 3 days, no agent
    sold_this_month: int = 0


class NeedsActionResponse(BaseModel):
    window_days: int
    kpis: NeedsActionKpis
    buckets: List[NeedsActionBucket] = []


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


# ─── Manual Lead Entry ────────────────────────────────────────────────────────

class ManualLeadCreateRequest(BaseModel):
    guest_name: str = Field(..., min_length=1, max_length=255)
    # At least one of phone/email required -- validated in the service layer,
    # since identity_service needs a real signal to resolve/create the guest.
    phone: Optional[str] = None
    email: Optional[str] = None
    source: str = "walk_in"   # InquirySource value -- agent picks the real one in the form
    property_id: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None
    assigned_to: Optional[str] = None


class ManualLeadCreateResponse(BaseModel):
    inquiry_id: str
    guest_id: str
    stage_key: Optional[str] = None
