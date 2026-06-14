"""
Inquiry360 — Additional tables that elevate Inquiry to a first-class sales lifecycle entity.

New tables:
  inquiry_stage_log      — full stage transition history
  inquiry_quotes         — multi-revision quote history
  inquiry_property_links — properties proposed / shortlisted / booked within an inquiry
"""

import enum
from sqlalchemy import Column, String, Text, Numeric, Boolean, DateTime, ForeignKey, Index
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class InquiryStageLog(Base, TimestampMixin, TenantMixin):
    """
    Immutable log of every stage transition for an inquiry.
    Enables funnel velocity analysis (time between stages).
    """
    __tablename__ = "inquiry_stage_log"

    id           = Column(String, primary_key=True, default=gen_uuid)
    tenant_id    = Column(String, nullable=False, index=True)
    inquiry_id   = Column(String, ForeignKey("inquiries.id"), nullable=False, index=True)

    from_stage   = Column(String(30), nullable=True)   # null when inquiry is first created
    to_stage     = Column(String(30), nullable=False)
    changed_by   = Column(String, nullable=True)        # user_id | "system" | "ai"
    changed_at   = Column(DateTime(timezone=True), nullable=False)
    reason       = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_inquiry_stage_log_inquiry", "inquiry_id"),
    )


class InquiryQuote(Base, TimestampMixin, TenantMixin):
    """
    Versioned quote history for an inquiry.
    The inquiry.quoted_amount field reflects the latest active quote.
    """
    __tablename__ = "inquiry_quotes"

    id           = Column(String, primary_key=True, default=gen_uuid)
    tenant_id    = Column(String, nullable=False, index=True)
    inquiry_id   = Column(String, ForeignKey("inquiries.id"), nullable=False, index=True)

    amount       = Column(Numeric(12, 2), nullable=False)
    currency     = Column(String(3), default="INR", nullable=False)
    valid_until  = Column(DateTime(timezone=True), nullable=True)

    pdf_url      = Column(Text, nullable=True)
    notes        = Column(Text, nullable=True)
    created_by   = Column(String, nullable=True)   # user_id
    is_active    = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_inquiry_quotes_inquiry", "inquiry_id"),
    )


class PropertyLinkType(str, enum.Enum):
    PROPOSED    = "proposed"
    SHORTLISTED = "shortlisted"
    BOOKED      = "booked"


class InquiryPropertyLink(Base, TimestampMixin, TenantMixin):
    """
    Properties discussed, shared, or booked within an inquiry context.
    tracking_token links to property_share_events for attribution.
    """
    __tablename__ = "inquiry_property_links"

    id             = Column(String, primary_key=True, default=gen_uuid)
    tenant_id      = Column(String, nullable=False, index=True)
    inquiry_id     = Column(String, ForeignKey("inquiries.id"), nullable=False, index=True)
    property_id    = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    link_type      = Column(String(20), default=PropertyLinkType.PROPOSED, nullable=False)
    tracking_token = Column(String(64), nullable=True, index=True)  # FK → property share events
    linked_at      = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_inquiry_property_links_inquiry", "inquiry_id"),
        Index("ix_inquiry_property_links_token", "tracking_token"),
    )
