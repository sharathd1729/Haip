"""Partnerships tables (agency M7): creators, creator (barter) deals, OTA listing copy drafts.

A creator's contact details are NOT kept here: when a comped stay is booked, the phone or email goes through
identity_service onto a guest record (DPDP consent, erasure and merging all work as for any guest), and the creator row
only points at that guest.
"""
from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class MarketingCreator(Base, TimestampMixin):
    __tablename__ = "marketing_creators"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    platform = Column(String(20), nullable=False, default="instagram")
    handle = Column(String(40), nullable=False)
    name = Column(String(120), nullable=True)
    followers = Column(Integer, nullable=True)                 # as reported, never scraped
    niche = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    guest_id = Column(String, nullable=True)                   # set when their first comped stay is booked
    status = Column(String(20), nullable=False, default="active")   # active | archived
    created_by = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "platform", "handle", name="uq_marketing_creators_handle"),)


class MarketingCreatorDeal(Base, TimestampMixin):
    """request -> approved (a person signs off the free stay) -> booked (a comped Stay exists) -> delivered (every
    deliverable posted with an ASCI label) | cancelled. Bookings it brings are traced by its utm_campaign ("cr-...")."""
    __tablename__ = "marketing_creator_deals"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    creator_id = Column(String, ForeignKey("marketing_creators.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="requested")
    property_id = Column(String, nullable=True)
    check_in = Column(Date, nullable=True)
    check_out = Column(Date, nullable=True)
    guests = Column(Integer, nullable=False, default=2)
    comp_value_inr = Column(Integer, nullable=False, default=0)
    deliverables = Column(JSON, nullable=False)                # [{kind, due, url, caption_label, delivered_at, asci_ok}]
    notes = Column(Text, nullable=True)
    stay_id = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class MarketingOtaCopy(Base, TimestampMixin):
    """Listing copy drafted for an OTA (no OTA API: a person pastes it in). Re-validated, price policy applied."""
    __tablename__ = "marketing_ota_copies"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, nullable=False)
    platform = Column(String(20), nullable=False)              # airbnb | booking | makemytrip
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed
    body = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    model = Column(String(120), nullable=True)
    prompt_version = Column(String(60), nullable=True)
    created_by = Column(String, nullable=True)
