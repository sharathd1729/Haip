"""
Ask HAIP models — Intelligence Analyst session & findings persistence.
"""
from sqlalchemy import Column, String, Text, Integer, Numeric, DateTime, JSON, ForeignKey
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class AskHaipSession(Base, TimestampMixin, TenantMixin):
    """One Ask HAIP question session — stores intent detection and paths."""
    __tablename__ = "ask_haip_sessions"

    id           = Column(String, primary_key=True, default=gen_uuid)
    tenant_id    = Column(String, nullable=False, index=True)
    user_id      = Column(String, nullable=True)
    question     = Column(Text, nullable=False)
    intent_json  = Column(JSON, nullable=True)      # detected intent object
    paths_generated = Column(JSON, nullable=True)   # list of path templates
    range_days   = Column(Integer, default=30)
    property_ids = Column(JSON, nullable=True)      # list[str] | null


class AskHaipFinding(Base, TimestampMixin, TenantMixin):
    """Cached RCA result — keyed by question_hash for 1hr deduplication."""
    __tablename__ = "ask_haip_findings"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False, index=True)
    session_id    = Column(String, ForeignKey("ask_haip_sessions.id"), nullable=True)
    question_hash = Column(String(64), nullable=False, index=True)
    findings_json = Column(JSON, nullable=True)
    agents_used   = Column(JSON, nullable=True)     # list[str]
    range_days    = Column(Integer, nullable=True)
    property_ids  = Column(JSON, nullable=True)
    confidence    = Column(Numeric(3, 2), nullable=True)
    expires_at    = Column(DateTime(timezone=True), nullable=True)


class AskHaipReport(Base, TimestampMixin, TenantMixin):
    """Generated report — weekly/monthly/property/etc."""
    __tablename__ = "ask_haip_reports"

    id           = Column(String, primary_key=True, default=gen_uuid)
    tenant_id    = Column(String, nullable=False, index=True)
    report_type  = Column(String(30), nullable=False)  # executive|weekly|monthly|...
    period_start = Column(String(10), nullable=True)   # YYYY-MM-DD
    period_end   = Column(String(10), nullable=True)
    title        = Column(String(255), nullable=True)
    html_content = Column(Text, nullable=True)
    pdf_s3_key   = Column(Text, nullable=True)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
