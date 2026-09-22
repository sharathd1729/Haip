"""
Ask HAIP models — Intelligence Analyst session & findings persistence.
"""
from sqlalchemy import Column, String, Text, Integer, Numeric, DateTime, JSON, ForeignKey
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class AskHaipFreeformQuery(Base, TimestampMixin, TenantMixin):
    """
    Audit trail for the free-form NL->SQL analyst
    (ask_haip_freeform_service.py). One row per attempt, including rejected
    ones -- this is the record CLAUDE.md's "audit event written if
    destructive or permission-sensitive" rule requires for the single
    riskiest data-access path in the app. Never edited after insert.
    """
    __tablename__ = "ask_haip_freeform_queries"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False, index=True)
    user_id       = Column(String, nullable=True)
    question      = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    status        = Column(String(20), nullable=False)  # ok | rejected | timeout | error
    reject_reason = Column(Text, nullable=True)
    row_count     = Column(Integer, nullable=True)
    duration_ms   = Column(Integer, nullable=True)
    chart_spec    = Column(JSON, nullable=True)
