"""Metered usage per tenant (LLM tokens, rendered creatives, later publishes and site traffic).

Append-only. Written from Phase 1 so usage-based pricing (Phase 4) starts with real history instead of estimates.
"""
from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, String

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class UsageEvent(Base, TimestampMixin):
    __tablename__ = "usage_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    module = Column(String(40), nullable=False)        # marketing_studio | website_builder | ...
    kind = Column(String(40), nullable=False)          # llm_tokens | creative_render | ...
    provider = Column(String(40), nullable=True)
    model = Column(String(120), nullable=True)
    units = Column(Integer, nullable=False, default=0)          # tokens, renders, ...
    input_units = Column(Integer, nullable=True)
    output_units = Column(Integer, nullable=True)
    ref_type = Column(String(40), nullable=True)
    ref_id = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)

    __table_args__ = (Index("ix_usage_events_tenant_module_created", "tenant_id", "module", "created_at"),)
