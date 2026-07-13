"""
Tenant-owned pipeline stage catalog — replaces the hardcoded InquiryStage
enum with real per-tenant authoring (add/remove/reorder stages), following
the same tenant-scoped-catalog pattern as modules/workspace_modules
(migration 031).

inquiries.stage (enum) is being migrated to inquiries.stage_id (FK here).
Both columns coexist during the migration; see the Leads360 restructure
plan for the phased cutover.
"""
from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, UniqueConstraint, Index
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class PipelineStage(Base, TimestampMixin, TenantMixin):
    __tablename__ = "pipeline_stages"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    key = Column(String(40), nullable=False)     # slug, unique per tenant
    label = Column(String(80), nullable=False)
    color = Column(String(7), nullable=False, default="#6366f1")
    order = Column(Integer, nullable=False, default=0)

    is_default_entry = Column(Boolean, nullable=False, default=False)  # exactly one TRUE per tenant
    is_closed_won = Column(Boolean, nullable=False, default=False)
    is_closed_lost = Column(Boolean, nullable=False, default=False)

    created_by = Column(String, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_pipeline_stage_tenant_key"),
        Index("ix_pipeline_stages_tenant_order", "tenant_id", "order"),
    )
