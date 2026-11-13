"""Channel manager via Channex (migration 205; services/channex_service.py)."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class ChannexMapping(Base, TimestampMixin, TenantMixin):
    """One HAIP unit (a villa, a caravan) linked to a Channex property / room type / rate plan."""

    __tablename__ = "channex_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "property_id", name="uq_channex_mappings_property"),
        UniqueConstraint("tenant_id", "channex_room_type_id", name="uq_channex_mappings_room_type"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False)
    channex_property_id = Column(String(64), nullable=False)
    channex_room_type_id = Column(String(64), nullable=False)
    channex_rate_plan_id = Column(String(64), nullable=True)
    push_rates = Column(Boolean, nullable=False, default=False)  # off until the owner checks HAIP's rates for this unit
    last_pushed_at = Column(DateTime(timezone=True), nullable=True)
    last_push_error = Column(Text, nullable=True)


class ChannexBookingLink(Base, TimestampMixin, TenantMixin):
    """One Channex booking and the HAIP Stay it became; last_revision_id makes a re-delivered revision a no-op."""

    __tablename__ = "channex_booking_links"
    __table_args__ = (UniqueConstraint("tenant_id", "channex_booking_id", name="uq_channex_booking_links_booking"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    channex_booking_id = Column(String(64), nullable=False)
    stay_id = Column(String, ForeignKey("stays.id"), nullable=True)
    last_revision_id = Column(String(64), nullable=True)
    status = Column(String(20), nullable=True)
    ota_name = Column(String(80), nullable=True)
    ota_reservation_code = Column(String(120), nullable=True)
