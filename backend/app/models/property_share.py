"""
Property Sharing Intelligence — tracking viral property link journeys.

Tables:
  property_shares       — one row per share action (link generated)
  property_share_events — one row per downstream event (view, forward, shortlist, inquiry)

Events flow:
  property.shared → property.viewed → property.revisited
                                    → property.forwarded → property.viewed (new viewer)
                                    → property.shortlisted
                                    → property.inquiry_created
"""

import enum
import secrets
from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime, Index
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


def gen_tracking_token() -> str:
    """Generate a URL-safe tracking token (16 bytes = 22 base64 chars)."""
    return secrets.token_urlsafe(16)


class ShareChannel(str, enum.Enum):
    WHATSAPP  = "whatsapp"
    INSTAGRAM = "instagram"
    SMS       = "sms"
    EMAIL     = "email"
    LINK      = "link"   # generic shareable link


class ShareEventType(str, enum.Enum):
    SHARED      = "shared"
    VIEWED      = "viewed"
    REVISITED   = "revisited"
    FORWARDED   = "forwarded"
    SHORTLISTED = "shortlisted"
    INQUIRY_CREATED = "inquiry_created"


class PropertyShare(Base, TimestampMixin, TenantMixin):
    """
    One row per share action — the originating event that generates a tracking token.
    """
    __tablename__ = "property_shares"

    id              = Column(String, primary_key=True, default=gen_uuid)
    tenant_id       = Column(String, nullable=False, index=True)
    property_id     = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    shared_by_gid   = Column(String, nullable=True, index=True)   # guest or staff user
    channel         = Column(String(20), nullable=True)            # ShareChannel value
    campaign_id     = Column(String, nullable=True, index=True)    # if campaign-triggered

    tracking_token  = Column(String(64), unique=True, nullable=False,
                             default=gen_tracking_token, index=True)

    # Aggregate counters (updated by event processor)
    total_views     = Column(Integer, default=0, nullable=False)
    total_revisits  = Column(Integer, default=0, nullable=False)
    total_forwards  = Column(Integer, default=0, nullable=False)
    total_inquiries = Column(Integer, default=0, nullable=False)
    total_bookings  = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_property_shares_token", "tracking_token"),
        Index("ix_property_shares_property", "property_id", "tenant_id"),
    )


class PropertyShareEvent(Base, TimestampMixin, TenantMixin):
    """
    One row per downstream action on a share (view, forward, shortlist, inquiry).
    """
    __tablename__ = "property_share_events"

    id               = Column(String, primary_key=True, default=gen_uuid)
    tenant_id        = Column(String, nullable=False, index=True)

    share_id         = Column(String, ForeignKey("property_shares.id"),
                               nullable=False, index=True)
    event_type       = Column(String(30), nullable=False)        # ShareEventType value

    viewer_gid       = Column(String, nullable=True, index=True) # resolved guest, if known
    referrer_gid     = Column(String, nullable=True)             # who forwarded (if forward chain)
    session_id       = Column(String(128), nullable=True)        # browser session

    # For inquiry_created events
    inquiry_id       = Column(String, nullable=True, index=True)

    occurred_at      = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_property_share_events_share", "share_id"),
        Index("ix_property_share_events_viewer", "viewer_gid"),
    )
