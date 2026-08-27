from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Enum as SAEnum, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class ChannelType(str, enum.Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    VOICE = "voice"
    WEBCHAT = "webchat"
    EMAIL = "email"
    # K15 internal notes (inquiries.py's _get_or_create_notes_conversation)
    # already relied on channel="internal" for the notes Conversation, but
    # this member was never added -- any read-back through the ORM (e.g.
    # db.refresh(), a later query) raised a raw-string-to-enum KeyError.
    # Column is plain VARCHAR(30) at the DB level (migration 001), not a
    # native Postgres enum, so no migration is needed to add this.
    INTERNAL = "internal"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageDeliveryState(str, enum.Enum):
    """
    Lifecycle of an outbound message send (orthogonal to was_approved).

    pending   — row inserted, not yet enqueued
    queued    — Celery task has been dispatched
    sent      — Meta Cloud API returned 200 with a wamid
    delivered — Meta status webhook: delivered
    read      — Meta status webhook: read
    failed    — retry exhaustion or permanent 4xx from Meta
    rejected  — Meta returned an explicit error code (e.g. template rejected)
    """
    PENDING   = "pending"
    QUEUED    = "queued"
    SENT      = "sent"
    DELIVERED = "delivered"
    READ      = "read"
    FAILED    = "failed"
    REJECTED  = "rejected"


class Conversation(Base, TimestampMixin, TenantMixin):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)

    channel = Column(SAEnum(ChannelType), nullable=False, index=True)
    channel_conversation_id = Column(String(255), nullable=True, index=True)  # WA thread ID etc.
    is_open = Column(Boolean, default=True, nullable=False, index=True)

    # SLA
    first_response_at = Column(String, nullable=True)
    last_message_at = Column(String, nullable=True)
    sla_breached = Column(Boolean, default=False)

    # W14: Snooze
    snoozed_until = Column(DateTime(timezone=True), nullable=True)

    # O2: sample data flag
    is_sample = Column(Boolean, default=False, nullable=False, index=True)

    # AI Concierge
    ai_mode = Column(String(20), default="shadow")  # shadow / autonomous / off
    ai_draft = Column(Text, nullable=True)           # Pending AI reply

    # Set the first time a human agent sends/approves an outbound message in
    # this thread (conversations.py's send/send-template/approve-draft
    # endpoints). ai_mode_service.resolve_mode() checks this before the
    # tenant default -- a person actively working a lead forces shadow mode
    # (AI drafts suggestions, never auto-sends) regardless of the tenant's
    # autonomous default. See migration 092.
    human_owned = Column(Boolean, default=False, nullable=False)

    guest = relationship("Guest")
    inquiry = relationship("Inquiry", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", lazy="dynamic", order_by="Message.created_at")


class Message(Base, TimestampMixin, TenantMixin):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)

    direction = Column(SAEnum(MessageDirection), nullable=False)
    channel = Column(SAEnum(ChannelType), nullable=False)

    # Content
    body = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)
    media_type = Column(String(50), nullable=True)  # image/audio/video/document

    # Channel metadata
    channel_message_id = Column(String(255), nullable=True, index=True)
    channel_status = Column(String(50), nullable=True)  # sent/delivered/read/failed
    # T0.3: raw ad-attribution payload -- Instagram message.referral (Click-to-IG ads)
    # or media.ad_id/ad_title (Phase 1 comment ingestion). Not attribution rollups --
    # just storage of what Meta sent, per CLAUDE.md's FUTURE MODULES boundary.
    channel_metadata = Column(JSON, nullable=True)

    # AI
    is_ai_generated = Column(Boolean, default=False)
    ai_confidence = Column(String(10), nullable=True)
    was_approved = Column(Boolean, nullable=True)  # null = not AI, True/False = approved/rejected
    # AI Autonomy Plan Phase 1 ticket 4: what the bounded tool loop actually
    # fetched (check_availability/get_quote calls + results) while drafting
    # this message, if any -- carried through to ai_draft_outcomes at
    # approve/reject time. Null/empty for non-AI messages and for AI
    # messages drafted without grounding (intent wasn't availability/price,
    # or the grounding budget was exhausted).
    grounded_facts = Column(JSON, nullable=True)

    # HAIP Inbox prototype-wiring plan, ticket 4: a structured one-click
    # action (e.g. send_quote) alongside this draft, when the grounded loop
    # produced a full quote worth offering as a button -- RecommendedAction[]
    # shape, same as next_action_service.get_call_actions(). Null/empty
    # otherwise, never fabricated when no real quote was fetched.
    suggested_actions = Column(JSON, nullable=True)

    # Idempotency — prevents duplicate sends on network retry
    # Partial unique index (tenant_id, idempotency_key WHERE NOT NULL) added in migration 005
    idempotency_key = Column(String(64), nullable=True, index=False)

    # Delivery state — tracks the outbound send lifecycle independently of approval
    # NULL for inbound messages; defaults to 'pending' for outbound (migration 006)
    delivery_state = Column(
        SAEnum(MessageDeliveryState, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        default=None,  # set explicitly in send_message endpoint
    )
    delivery_error = Column(Text, nullable=True)  # last error from Meta API

    # Internal notes — W24: never delivered to guest
    is_internal = Column(Boolean, default=False, nullable=False)

    # O2: sample data flag
    is_sample = Column(Boolean, default=False, nullable=False, index=True)

    # True only when the AI sent this by itself, with no human in the loop.
    # Distinct from was_approved, which the inbox approve handler, the
    # one-click action and the auto-send path all set to True -- so it alone
    # cannot answer "what did the AI send unsupervised?" (migration 081).
    sent_autonomously = Column(Boolean, default=False, nullable=False)

    # Per-message intent the concierge classified while drafting
    # (availability_check | price_quote | faq_answer | complaint | general).
    # Persisted so the approve/reject paths can record it on the outcome row
    # too -- it was previously computed and thrown away, which left
    # ai_draft_outcomes.intent unpopulated by every caller (migration 082).
    ai_intent = Column(String(50), nullable=True)

    # Why this draft was held for human review instead of auto-sending --
    # the model's own self-reported reason_needs_human (e.g. off-topic
    # hand-off), or a fired deterministic guard's violation text (capacity/
    # price/availability hallucination, escalation, price leak, completion
    # timeout). NULL for anything that wasn't flagged needs_human. Added
    # after a real investigation hit a dead end: 31 of 95 drafts over 7
    # days scored above the autonomous threshold yet didn't auto-send, and
    # there was no way to tell why after the fact -- the reason only ever
    # existed in a log line that the next container restart erases.
    ai_needs_human_reason = Column(Text, nullable=True)

    # Reply-to-message — W5: quoted reply threading
    replied_to_message_id = Column(String, ForeignKey("messages.id"), nullable=True)

    # Scheduled send — W4
    scheduled_for = Column(String, nullable=True)  # ISO datetime string

    # Sender
    sender_id = Column(String, ForeignKey("users.id"), nullable=True)
    sender_name = Column(String(255), nullable=True)

    # Phase 2.5 agent-accountability instrumentation
    # (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.2): set once per inbound
    # message at the point the automation-routing decision is made
    # (ig_keyword_match / WhatsApp equivalent) -- matched_auto_replied |
    # matched_ai_drafted | no_match_ai_drafted | no_match_no_response.
    # ig_keyword_match.find_matching_rule() returns None with no side effect
    # by design, so a "no rule matched, no AI reply either" miss was
    # otherwise unrecoverable after the fact. Null for outbound messages and
    # for inbound messages ingested before this column existed.
    automation_outcome = Column(String(30), nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
