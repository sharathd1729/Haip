from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Numeric, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class ScoringMethod(str, enum.Enum):
    YES_NO = "yes_no"
    ZERO_THREE = "zero_three"
    AUTO_FAIL = "auto_fail"


class Rubric(Base, TimestampMixin, TenantMixin):
    __tablename__ = "rubrics"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    version = Column(String(20), default="1.0")
    is_default = Column(Boolean, default=False)
    criteria = Column(JSON, nullable=False)  # [{id, name, weight, method, description}]
    is_active = Column(Boolean, default=True)

    scores = relationship("CallScore", back_populates="rubric", lazy="dynamic")


class CallScore(Base, TimestampMixin, TenantMixin):
    __tablename__ = "call_scores"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    call_id = Column(String, ForeignKey("calls.id"), nullable=False, index=True)
    rubric_id = Column(String, ForeignKey("rubrics.id"), nullable=False)
    rubric_snapshot = Column(JSON, nullable=False)  # Snapshot of rubric at scoring time

    # Overall
    total_score = Column(Numeric(5, 2), nullable=False)
    max_score = Column(Numeric(5, 2), nullable=False)
    percentage = Column(Numeric(5, 2), nullable=False)
    has_auto_fail = Column(Boolean, default=False)

    # Per-criterion results
    criterion_scores = Column(JSON, nullable=False)  # [{criterion_id, score, evidence_span, confidence}]

    # AI metadata
    model_used = Column(String(50), nullable=False)
    ai_confidence = Column(Numeric(3, 2), nullable=True)
    processing_time_ms = Column(String, nullable=True)

    # Override
    is_overridden = Column(Boolean, default=False)
    override_scores = Column(JSON, nullable=True)
    override_reason = Column(Text, nullable=True)
    overridden_by = Column(String, ForeignKey("users.id"), nullable=True)
    overridden_at = Column(String, nullable=True)

    call = relationship("Call", back_populates="scores")
    rubric = relationship("Rubric", back_populates="scores")
