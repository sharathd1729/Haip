"""
Inquiry360 — Additional tables that elevate Inquiry to a first-class sales lifecycle entity.

New tables:
  inquiry_stage_log      — full stage transition history
  inquiry_quotes         — multi-revision quote history
  inquiry_property_links — properties proposed / shortlisted / booked within an inquiry
"""

import enum
from sqlalchemy import JSON, Column, Date, Integer, SmallInteger, String, Text, Numeric, Boolean, DateTime, ForeignKey, Index
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

    pdf_url      = Column(Text, nullable=True)   # sent quote PDF: the storage key (media_storage.upload_quote_pdf), on the primary option
    notes        = Column(Text, nullable=True)
    created_by   = Column(String, nullable=True)   # user_id
    is_active    = Column(Boolean, default=True, nullable=False)

    # Issued-quote snapshot (migration 125): what the guest was actually quoted, so a later price change never alters it.
    package_key  = Column(String(60), nullable=True)
    check_in     = Column(Date, nullable=True)
    check_out    = Column(Date, nullable=True)
    guests       = Column(Integer, nullable=True)
    snapshot     = Column(JSON, nullable=True)       # lines, totals, inputs, inclusions/exclusions (package_pricing_service.to_snapshot)
    record_refs  = Column(JSON, nullable=True)       # [{kind, key, version, record_id}] the quote was built from
    params_hash  = Column(String(64), nullable=True) # same inputs + same record versions -> same hash (idempotent issue)
    status       = Column(String(20), nullable=True) # issued | superseded | expired | accepted | withdrawn
    # Options (migration 140): a quote has a primary option (rank 1) and may have a fallback (rank 2), each priced on its own.
    # Both share option_group_id = the primary's id. Older rows: rank 1, no group.
    option_rank     = Column(SmallInteger, nullable=False, default=1, server_default="1")
    option_group_id = Column(String, nullable=True, index=True)
    # Rate calculator (migration 148): how it reached the guest ("sent" | "copied"; NULL = saved only) and who approved a price
    # lowered past the tenant's limit (status "pending_approval" until then).
    shared_via   = Column(String(20), nullable=True)
    shared_at    = Column(DateTime(timezone=True), nullable=True)
    shared_message_id = Column(String, nullable=True)   # the WhatsApp Message that carried it, when sent (migration 151)
    approved_by  = Column(String, nullable=True)
    approved_at  = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_inquiry_quotes_inquiry", "inquiry_id"),
    )


class PropertyLinkType(str, enum.Enum):
    PROPOSED    = "proposed"
    SHORTLISTED = "shortlisted"
    BOOKED      = "booked"


