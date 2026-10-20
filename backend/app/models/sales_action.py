"""A quote the AI sales agent prepared for a lead, and what happened to it (migration 142).

One row per prepared quote group: the agent priced the guest's requirement from published records, issued it on the lead
(InquiryQuote, the same table the staff quote builder writes) and either waits for a person (``suggest``) or sends it itself
(``autopilot``) through quote_send_service. The row binds the approval to that exact quote: Approve sends THAT quote group,
never a recomputed one, and a quote that is no longer valid cannot be sent.

status:  pending      waiting for a person (suggest, or an autopilot run that did not pass every guard)
         sending      approved (or autopilot) and handed to quote_send_service
         sent         links made and the WhatsApp quote queued
         rejected     a person dismissed it
         superseded   the guest changed the requirement; a newer action replaced it
         failed       the send was refused (reason in ``last_error``); a person can retry from the quote builder
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid

STATUSES = ("pending", "sending", "sent", "rejected", "superseded", "failed")
LIVE_STATUSES = ("pending", "sending", "sent")


class SalesAction(Base, TimestampMixin, TenantMixin):
    __tablename__ = "sales_actions"
    __table_args__ = (
        Index("ix_sales_actions_tenant_inquiry", "tenant_id", "inquiry_id"),
        Index("ix_sales_actions_tenant_status", "tenant_id", "status"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=False)
    conversation_id = Column(String, nullable=True, index=True)
    message_id = Column(String, nullable=True)                 # the AI draft that told the guest about it
    quote_id = Column(String, nullable=False)                  # the primary InquiryQuote of the group
    kind = Column(String(20), nullable=False, default="send_quote")
    mode = Column(String(12), nullable=False)                  # suggest | autopilot (what the tenant setting was)
    status = Column(String(12), nullable=False, default="pending")
    requirement_key = Column(String(64), nullable=False)       # sha256 of what the guest asked for (plan, dates, party, route)
    summary = Column(JSON, nullable=False, default=dict)       # package, dates, guests, total, advance, fallback (from the snapshot)
    hold_reasons = Column(JSON, nullable=False, default=list)  # why autopilot did not send it itself
    last_error = Column(Text, nullable=True)
    decided_by = Column(String, nullable=True)                 # user id; NULL = the agent
    decided_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(JSON, nullable=True)                       # quote_send_service's answer (message status, link ids)
