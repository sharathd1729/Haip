from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Integer, Numeric
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, SoftDeleteMixin, gen_uuid


class Guest(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "guests"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Identity (E.164 phone is primary key for dedup)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=True)
    alt_phone = Column(String(20), nullable=True)

    # Profile
    city = Column(String(100), nullable=True)
    nationality = Column(String(100), nullable=True)
    language_pref = Column(String(10), default="en")
    vip_tier = Column(String(20), nullable=True)  # silver/gold/platinum

    # Analytics (updated async)
    total_stays = Column(Integer, default=0)
    total_inquiries = Column(Integer, default=0)
    lifetime_value = Column(Numeric(12, 2), default=0)
    predicted_csat = Column(Numeric(3, 2), nullable=True)
    last_contact_at = Column(String, nullable=True)  # ISO datetime string

    # Tags + preferences (freeform)
    tags = Column(JSON, default=list)
    preferences = Column(JSON, default=dict)  # dietary, room-type, etc.

    # DPDP consent
    marketing_consent = Column(Boolean, default=False)
    recording_consent = Column(Boolean, default=True)

    # Unique per tenant
    __table_args__ = (
        # (tenant_id, phone) must be unique
        {"schema": None},
    )

    tenant = relationship("Tenant", back_populates="guests")
    inquiries = relationship("Inquiry", back_populates="guest", lazy="dynamic")
    calls = relationship("Call", back_populates="guest", lazy="dynamic")
    stays = relationship("Stay", back_populates="guest", lazy="dynamic")
    consents = relationship("Consent", back_populates="guest", lazy="dynamic")
