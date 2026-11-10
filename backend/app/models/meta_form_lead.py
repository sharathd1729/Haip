"""One row per Meta lead-form submission HAIP has imported: the dedup key (a lead is imported once) and the link from
the ad that produced it to the lead it became. Holds ids only; the guest's answers live on the enquiry."""

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class MetaFormLead(Base, TimestampMixin):
    __tablename__ = "meta_form_leads"
    __table_args__ = (UniqueConstraint("tenant_id", "leadgen_id", name="uq_meta_form_leads_tenant_leadgen"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    leadgen_id = Column(String(64), nullable=False)
    form_id = Column(String(64), nullable=True)
    form_name = Column(String(255), nullable=True)
    page_id = Column(String(64), nullable=True)
    ad_id = Column(String(64), nullable=True)
    adset_id = Column(String(64), nullable=True)
    campaign_id = Column(String(64), nullable=True)
    platform = Column(String(20), nullable=True)  # fb | ig, as Meta reports it
    lead_created_at = Column(DateTime(timezone=True), nullable=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="created")  # created | attached | no_contact
