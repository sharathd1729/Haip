from sqlalchemy import Column, String, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class Transcript(Base, TimestampMixin, TenantMixin):
    __tablename__ = "transcripts"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    call_id = Column(String, ForeignKey("calls.id"), nullable=False, unique=True, index=True)

    provider = Column(String(50), nullable=False)   # sarvam | deepgram | groq | whisper
    language = Column(String(20), nullable=True)    # BCP-47: hi-IN | en-IN | hi-en (code-mixed)
    script_type = Column(String(20), nullable=True) # devanagari | roman | mixed (Sarvam output)
    redacted = Column(Boolean, default=False, nullable=False)

    # [{ "speaker": "agent|guest", "t0": float, "t1": float, "text": str }]
    turns = Column(Text, nullable=True)             # JSON stored as text
    raw_text = Column(Text, nullable=True)
    embedding = Column(Vector(1024), nullable=True) # pgvector

    call = relationship("Call", back_populates="transcript")
