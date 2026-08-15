from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Integer, Numeric, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class CallDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallDisposition(str, enum.Enum):
    HOT = "hot"
    QUOTED = "quoted"
    BOOKED = "booked"
    LOST = "lost"
    CALLBACK = "callback"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"


class RecordingStatus(str, enum.Enum):
    """
    Lifecycle of the call recording fetch pipeline.

    pending           — IVR webhook received; recording URL noted; fetch not yet attempted
    fetching          — download from IVR provider is in-flight
    available         — file stored in S3 / R2 successfully
    missing_retry_1   — first attempt failed; retry scheduled at +1 h
    missing_retry_2   — second attempt failed; retry scheduled at +6 h
    missing_retry_3   — third attempt failed; retry scheduled at +24 h
    permanently_missing — all retries exhausted; no further attempts will be made
    """
    PENDING             = "pending"
    FETCHING            = "fetching"
    AVAILABLE           = "available"
    MISSING_RETRY_1     = "missing_retry_1"
    MISSING_RETRY_2     = "missing_retry_2"
    MISSING_RETRY_3     = "missing_retry_3"
    PERMANENTLY_MISSING = "permanently_missing"


class Call(Base, TimestampMixin, TenantMixin):
    __tablename__ = "calls"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True, index=True)
    agent_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)

    # IVR data
    ivr_provider = Column(String(50), nullable=False)  # callerdesk / acefone
    ivr_call_id = Column(String(255), nullable=False, unique=True, index=True)
    direction = Column(SAEnum(CallDirection), nullable=False)
    from_number = Column(String(20), nullable=False)
    to_number = Column(String(20), nullable=False)
    duration_seconds = Column(Integer, default=0)
    started_at = Column(String, nullable=True)
    ended_at = Column(String, nullable=True)

    # Phase 2.5 agent-accountability instrumentation
    # (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.3): self-referential
    # link from a missed inbound call to the later outbound call (to the
    # same guest, within the matching window) that recovered it. Nullable —
    # unset until a matching outbound call is recorded, and stays null
    # forever for calls that were never missed or never recovered. Answers
    # "did we call them back" without which the schema has no way to.
    recovered_by_call_id = Column(String, ForeignKey("calls.id"), nullable=True)

    # Recording
    recording_url_ivr = Column(Text, nullable=True)  # IVR provider URL
    recording_s3_key = Column(Text, nullable=True)   # Our S3 key
    recording_fetched = Column(Boolean, default=False)  # legacy; use recording_status instead
    recording_status = Column(
        SAEnum(RecordingStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        default=RecordingStatus.PENDING,
    )
    recording_error = Column(Text, nullable=True)  # last error from fetch

    # Processing status
    transcription_status = Column(String(20), default="pending")  # pending/processing/done/failed
    ai_score_status = Column(String(20), default="pending")

    # AI output
    # NOTE: legacy inline transcript JSON — the canonical store is the Transcript table.
    # Renamed from "transcript" → "transcript_json" to avoid clashing with the
    # transcript relationship below. The DB column name stays "transcript" so no
    # migration is needed.
    transcript_json = Column("transcript", JSON, nullable=True)   # [{speaker, text, start, end}]
    ai_summary = Column(Text, nullable=True)
    ai_disposition = Column(SAEnum(CallDisposition), nullable=True)
    ai_next_action = Column(Text, nullable=True)
    ai_score = Column(Numeric(5, 2), nullable=True)   # 0-100

    # M5+ WS1: structured, clickable version of ai_next_action. Derived
    # programmatically from existing data (e.g. a pending AI-drafted
    # WhatsApp reply for this call's guest) -- not a new LLM classification
    # call. See call_service.py::derive_recommended_action(). Additive:
    # ai_next_action (free text) is unchanged and still always populated.
    recommended_action_type = Column(String(30), nullable=True)     # e.g. "send_whatsapp_draft"
    recommended_action_target_id = Column(String, nullable=True)    # e.g. a Message.id

    # Human override
    human_disposition = Column(SAEnum(CallDisposition), nullable=True)
    disposition_note = Column(Text, nullable=True)
    disposition_set_by = Column(String, nullable=True)

    # Cost tracking
    transcription_cost_usd = Column(Numeric(8, 4), default=0)
    llm_cost_usd = Column(Numeric(8, 4), default=0)
    storage_cost_usd = Column(Numeric(8, 4), default=0)

    # O2: sample data flag
    is_sample = Column(Boolean, default=False, nullable=False, index=True)

    # Language
    detected_language = Column(String(10), nullable=True)
    is_code_mixed = Column(Boolean, default=False)

    # ── Layer 2: Intent & Outcome (Call Analysis) ─────────────────────────────
    occasion   = Column(String(50),  nullable=True)          # honeymoon|anniversary|birthday|corporate|family|solo
    intent_tag = Column(String(30),  nullable=True, index=True)  # Phase 3: normalized bucket
    budget_signal = Column(String(100), nullable=True)    # "That's high" / "Okay works" / "Can you do better?"
    decision_stage = Column(String(50), nullable=True)    # first_inquiry|comparing|ready_to_book
    competitor_mentioned = Column(String(255), nullable=True)  # StayVista, Airbnb, etc.
    conversion_probability = Column(Integer, nullable=True)    # 0–100
    lost_reason = Column(String(100), nullable=True)      # price|dates_unavailable|still_comparing|no_response|wrong_property

    # ── Dograh voice AI (migration 025) ──────────────────────────────────────
    voice_platform = Column(String(20), nullable=False, server_default="callerdesk")
    dograh_call_id = Column(String(255), nullable=True, unique=True)
    dograh_agent_id = Column(String(255), nullable=True)
    sip_trunk_provider = Column(String(50), nullable=True)
    transfer_to_human = Column(Boolean, nullable=False, default=False)
    transfer_reason = Column(String(255), nullable=True)

    guest = relationship("Guest", back_populates="calls")
    inquiry = relationship("Inquiry", back_populates="calls")
    agent = relationship("User", foreign_keys=[agent_id])
    scores = relationship("CallScore", back_populates="call", lazy="dynamic")
    transcript = relationship("Transcript", back_populates="call", uselist=False)
