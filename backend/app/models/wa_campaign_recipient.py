"""One row per guest a WhatsApp campaign was sent to: what happened to that
message (sent / delivered / read / failed) and, when it failed, why.

Before this table a campaign kept only four counters, delivered and read were
never written, and Meta's failure reason was thrown away.
"""
from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class WACampaignRecipient(Base, TimestampMixin, TenantMixin):
    __tablename__ = "wa_campaign_recipients"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    campaign_id = Column(String, nullable=False, index=True)
    subscriber_id = Column(String, nullable=True)
    guest_id = Column(String, nullable=True, index=True)     # set when the audience was CRM leads
    phone = Column(String(30), nullable=False)
    name = Column(String(255), nullable=True)      # as it was when the campaign ran

    # queued | sent | delivered | read | failed
    status = Column(String(20), nullable=False, default="queued")
    wa_message_id = Column(String(255), nullable=True, index=True)   # Meta's wamid -- how a status callback finds this row
    error_code = Column(String(30), nullable=True)
    error_reason = Column(String(500), nullable=True)

    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # A guest gets a campaign once: also what stops a retried run from
        # sending to everyone a second time.
        UniqueConstraint("campaign_id", "phone", name="uq_wa_campaign_recipient_phone"),
        Index("ix_wa_campaign_recipients_campaign_status", "campaign_id", "status"),
    )
