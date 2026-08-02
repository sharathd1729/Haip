"""Capability registry (HAIP_MCP_Connector_Plan.md §2, Phase 1).

Capabilities answer "may this role touch this domain?" -- they do NOT
answer "which rows?" (row-scope ABAC like property_scope or "concierge
sees own leads only" is a deliberate v1 gap, see the plan's §2.5).

`Capability` is a global, un-tenanted catalogue (same pattern as `Module`
in models/module.py). `RoleCapability` is the tenant-owned override
matrix (same tenant-scoped-catalog pattern as `PipelineStage`) -- seeded
per tenant at registration from the plan's §2.3 default matrix, editable
per-tenant afterward.
"""
from sqlalchemy import Column, String, Boolean, ForeignKey, UniqueConstraint, Index
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Capability(Base):
    """Global capability catalogue -- one row per capability key, never
    tenant-scoped, no RLS (same reasoning as Module: every tenant needs to
    see the same catalogue to build/edit its own role matrix)."""
    __tablename__ = "capabilities"

    key = Column(String(64), primary_key=True)  # "<domain>.<action>[.<qualifier>]"
    label = Column(String(120), nullable=False)
    category = Column(String(40), nullable=False)  # leads|conversations|calls|guests|bookings|revenue|analytics|qa|admin
    is_write = Column(Boolean, nullable=False, default=False)
    module_code = Column(String(50), nullable=True)  # null = always available regardless of module entitlement
    risk = Column(String(10), nullable=False, default="low")  # low|medium|high -- drives confirmation UX


class RoleCapability(Base, TimestampMixin):
    """Tenant-scoped override matrix. A tenant with zero rows must be
    treated as unprovisioned and fail closed (no capabilities) -- same
    lesson as migration 035/036's workspace_modules backfill, see this
    table's own migration for the backfill that keeps that from happening."""
    __tablename__ = "role_capabilities"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    role = Column(String(32), nullable=False)  # UserRole value
    capability_key = Column(String(64), ForeignKey("capabilities.key"), nullable=False)
    allowed = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "role", "capability_key", name="uq_role_capabilities_tenant_role_key"),
        Index("ix_role_capabilities_tenant_role", "tenant_id", "role"),
    )
