"""
Guest Identity Graph — Progressive Identity Resolution

Each row maps one identity signal to a canonical Guest ID.
No single signal is required; the GID is always canonical.

Supported identity_type values:
  instagram_user_id  — Meta IG user identifier
  whatsapp_number    — E.164 phone used as WhatsApp ID
  email              — lowercase trimmed email
  phone              — E.164 phone number
  booking_id         — booking UUID or external booking reference
  channel_thread_id  — namespaced OTA thread, e.g. "airbnb:AB-12345"
  ota_guest_id       — OTA-platform guest identifier
  call_record_id     — call UUID (phone matched after the fact)
  website_session_id — future: UTM + cookie session
  device_fingerprint — future: browser/device fingerprint
"""

import enum
from sqlalchemy import Column, String, Float, DateTime, UniqueConstraint, Index
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class IdentityType(str, enum.Enum):
    INSTAGRAM_USER_ID  = "instagram_user_id"
    WHATSAPP_NUMBER    = "whatsapp_number"
    EMAIL              = "email"
    PHONE              = "phone"
    BOOKING_ID         = "booking_id"
    CHANNEL_THREAD_ID  = "channel_thread_id"
    OTA_GUEST_ID       = "ota_guest_id"
    CALL_RECORD_ID     = "call_record_id"
    WEBSITE_SESSION_ID = "website_session_id"
    DEVICE_FINGERPRINT = "device_fingerprint"


# Initial confidence weights per signal type (from architecture doc)
SIGNAL_CONFIDENCE: dict[str, float] = {
    IdentityType.INSTAGRAM_USER_ID:  0.70,
    IdentityType.WHATSAPP_NUMBER:    0.85,
    IdentityType.EMAIL:              0.75,
    IdentityType.PHONE:              0.90,
    IdentityType.BOOKING_ID:         0.95,
    IdentityType.CHANNEL_THREAD_ID:  0.80,
    IdentityType.OTA_GUEST_ID:       0.85,
    IdentityType.CALL_RECORD_ID:     0.80,
    IdentityType.WEBSITE_SESSION_ID: 0.50,
    IdentityType.DEVICE_FINGERPRINT: 0.40,
}

MERGE_THRESHOLD  = 0.85   # auto-merge
REVIEW_THRESHOLD = 0.65   # flag for manual review


class GuestIdentity(Base, TimestampMixin, TenantMixin):
    """One identity signal linked to a canonical Guest."""
    __tablename__ = "guest_identities"

    id             = Column(String, primary_key=True, default=gen_uuid)
    tenant_id      = Column(String, nullable=False, index=True)
    guest_id       = Column(String, nullable=False, index=True)  # FK → guests.id

    identity_type  = Column(String(50), nullable=False)
    identity_value = Column(String(512), nullable=False)   # normalized value
    source         = Column(String(100), nullable=True)    # instagram|whatsapp|rentalwise|airbnb|…

    # Confidence increases as more corroborating signals are added
    confidence     = Column(Float, nullable=False, default=0.70)

    first_seen_at  = Column(DateTime(timezone=True), nullable=True)
    last_seen_at   = Column(DateTime(timezone=True), nullable=True)
    verified_at    = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # One value per type per tenant — the uniqueness constraint
        UniqueConstraint("tenant_id", "identity_type", "identity_value",
                         name="uq_guest_identity_tenant_type_value"),
        Index("ix_guest_identities_guest", "tenant_id", "guest_id"),
    )
