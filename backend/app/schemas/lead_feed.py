"""Lead page "C · Chat" -- the one chronological thread for a lead (GET /leads/{id}/feed).

Every kind of thing that happened with this person lands in ONE list, oldest first, so the page reads like a
WhatsApp chat: messages, calls (with the AI call summary), quotes, bookings, stage changes, tasks and identity
merges. Built by services/lead_feed_service.py (one batched query per kind, tenant-scoped, capped at 50).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel

FeedKind = Literal["message", "call", "quote", "booking", "stage", "task", "merge"]


class FeedItemSchema(BaseModel):
    id: str
    kind: FeedKind
    at: datetime
    # message + call
    channel: Optional[str] = None            # whatsapp | instagram | ... (message); "call" for calls
    direction: Optional[str] = None          # inbound | outbound
    conversation_id: Optional[str] = None
    text: Optional[str] = None               # message body; stage / task / merge sentence
    media_type: Optional[str] = None
    sender_name: Optional[str] = None        # who sent it (agent, "AI reply", the guest)
    is_ai: bool = False
    is_draft: bool = False                   # an AI draft still waiting for a person (never sent)
    is_internal: bool = False                # an internal note, never sent to the guest
    is_template: bool = False
    delivery: Optional[str] = None           # pending | queued | sent | delivered | read | failed | rejected
    # call
    call_id: Optional[str] = None
    duration_seconds: Optional[int] = None
    answered: Optional[bool] = None
    summary: Optional[str] = None            # AI call summary
    summary_pending: bool = False            # answered, transcript / summary still being written
    has_recording: bool = False
    has_transcript: bool = False
    manual: bool = False                     # logged by hand (a call from the agent's own phone); its note is in `text`
    imported: bool = False                   # uploaded evidence: a message from a WhatsApp chat export, a call recording
    # quote
    quote_id: Optional[str] = None
    amount: Optional[float] = None
    label: Optional[str] = None              # package / trip name, or the booking's vehicle
    shared_via: Optional[str] = None         # sent | copied | None (saved only)
    status: Optional[str] = None             # quote: issued | superseded | ...; booking: confirmed | ...; task: open | done
    valid_until: Optional[datetime] = None
    valid_until_text: Optional[str] = None
    # booking
    booking_id: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    guests: Optional[int] = None
    amount_restricted: bool = False          # booking amounts need bookings.read
    # stage
    from_label: Optional[str] = None
    to_label: Optional[str] = None
    reason: Optional[str] = None
    # task
    task_id: Optional[str] = None
    due_date: Optional[datetime] = None
    # who did it (stage move, task, quote, merge)
    by_name: Optional[str] = None


class FeedChannelSchema(BaseModel):
    """One chat the page can reply on. `can_send` is False for the read-only personal WhatsApp mirror."""
    conversation_id: str
    channel: str
    last_inbound_at: Optional[datetime] = None
    last_outbound_at: Optional[datetime] = None
    can_send: bool = True
    ai_enabled: bool = True


class FeedBookingSchema(BaseModel):
    booking_id: str
    inquiry_id: Optional[str] = None
    property_name: Optional[str] = None
    check_in: str
    check_out: str
    status: str
    guests: int = 0
    total: Optional[float] = None
    paid: Optional[float] = None
    outstanding: Optional[float] = None
    payment_status: Optional[str] = None
    amount_restricted: bool = False


class FeedTaskSchema(BaseModel):
    task_id: str
    title: str
    due_date: Optional[datetime] = None
    is_done: bool = False
    priority: str = "medium"
    assignee_name: Optional[str] = None
    created_at: Optional[datetime] = None


class FeedMergeSchema(BaseModel):
    merge_id: str
    at: datetime
    reason: str
    by_name: Optional[str] = None
    undone: bool = False
    joined: List[str] = []                   # what came across: "2 calls", "1 conversation", ...


class FeedVehicleSchema(BaseModel):
    property_id: str
    name: str
    free: bool


class FeedContactSchema(BaseModel):
    phone_masked: Optional[str] = None       # the real number only via POST /leads/{id}/contact/reveal (audited)
    has_phone: bool = False
    has_whatsapp: bool = False
    has_instagram: bool = False
    email_masked: Optional[str] = None
    first_touch_channel: Optional[str] = None
    first_touch_at: Optional[datetime] = None


class FeedTripSchema(BaseModel):
    """Trip fields the lead detail does not carry. Edited with PATCH /inquiries/{id}."""
    route: Optional[str] = None
    pickup: Optional[str] = None
    special_requests: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_note: Optional[str] = None


class FeedFactsSchema(BaseModel):
    """What the next-step helper (frontend lib/leadNextStep.ts) needs, computed from the same rows as the thread."""
    last_inbound_at: Optional[datetime] = None
    last_outbound_at: Optional[datetime] = None       # a message a PERSON or the AI actually sent (drafts excluded)
    unanswered_outbound_calls: int = 0                # our calls in a row nobody picked up, since the last answered one
    missed_inbound_unreturned: bool = False           # they called, nobody answered, we have not called back since
    last_call_at: Optional[datetime] = None
    pending_drafts: int = 0


class LeadFeedSchema(BaseModel):
    inquiry_id: str
    guest_id: str
    items: List[FeedItemSchema] = []         # oldest first (a chat reads top to bottom)
    capped: bool = False                     # older items exist beyond these 50
    total_available: int = 0
    messages_restricted: bool = False        # the role lacks conversations.read: no message text is sent
    channels: List[FeedChannelSchema] = []
    bookings: List[FeedBookingSchema] = []
    tasks: List[FeedTaskSchema] = []
    merges: List[FeedMergeSchema] = []
    availability: List[FeedVehicleSchema] = []   # per vehicle, for the lead's dates (empty without dates)
    contact: FeedContactSchema = FeedContactSchema()
    trip: FeedTripSchema = FeedTripSchema()
    facts: FeedFactsSchema = FeedFactsSchema()


class RevealContactResponse(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
