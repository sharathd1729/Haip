"""
Lead Field Registry — Leads360 restructure Phase 3 (§4 of the plan).

Unifies two originally-separate asks (what fields show on a lead's detail
view, and what fields qualify a message as a lead) into one tenant-scoped
field catalog, following the modules/workspace_modules precedent.
"""
from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, UniqueConstraint
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class LeadFieldDefinition(Base, TimestampMixin, TenantMixin):
    __tablename__ = "lead_field_definitions"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    field_key = Column(String(40), nullable=False)     # e.g. "guest_count", "budget"
    label = Column(String(80), nullable=False)
    data_type = Column(String(20), nullable=False, default="text")   # text|number|date|date_range|currency|phone
    source = Column(String(20), nullable=False, default="custom")    # "column" | "custom"
    column_name = Column(String(40), nullable=True)    # set when source="column"

    show_in_detail = Column(Boolean, nullable=False, default=True)
    required_for_lead = Column(Boolean, nullable=False, default=False)
    display_order = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "field_key", name="uq_lead_field_tenant_key"),
    )
