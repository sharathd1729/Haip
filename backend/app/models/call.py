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

    # Recording
    recording_url_ivr = Column(Text, nullable=True)  # IVR provider URL
    recording_s3_key = Column(Text, nullable=True)   # Our S3 key
    recording_fetched = Column(Boolean, default=False)

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

    # Human override
    human_disposition = Column(SAEnum(CallDisposition), nullable=True)
    disposition_note = Column(Text, nullable=True)
    disposition_set_by = Column(String, nullable=True)

    # Cost tracking
    transcription_cost_usd = Column(Numeric(8, 4), default=0)
    llm_cost_usd = Column(Numeric(8, 4), default=0)
    storage_cost_usd = Column(Numeric(8, 4), default=0)

    # Language
    detected_language = Column(String(10), nullable=True)
    is_code_mixed = Column(Boolean, default=False)

    guest = relationship("Guest", back_populates="calls")
    inquiry = relationship("Inquiry", back_populates="calls")
    agent = relationship("User", foreign_keys=[agent_id])
    scores = relationship("CallScore", back_populates="call", lazy="dynamic")
    transcript = relationship("Transcript", back_populates="call", uselist=False)
