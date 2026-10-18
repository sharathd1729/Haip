"""Leads from HAIP's OWN public website (migration 145): book-demo, contact and property-assessment forms.

DOCUMENTED PLATFORM-LEVEL EXCEPTION to "every table has tenant_id + RLS": these rows belong to HAIP the company, not
to any customer workspace. The writer is an anonymous visitor (no tenant is known), and the only reader is the owner of
HAIP's own sales workspace (``PLATFORM_LEADS_TENANT_SLUG``) through ``GET /platform-leads``. The table therefore has
no ``tenant_id`` column and no tenant policy; ``workspace_tenant_id`` only records which workspace the lead was ALSO
copied into as a Leads360 inquiry (that copy lives in tenant tables under normal RLS).

Contains prospect PII (name, phone, email). Never logged; erasure requests come through the grievance form.
"""
from sqlalchemy import JSON, Boolean, Column, DateTime, Index, String, Text

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class PlatformLead(Base, TimestampMixin):
    __tablename__ = "platform_leads"
    __table_args__ = (
        Index("ix_platform_leads_ip_created", "ip_hash", "created_at"),
        Index("ix_platform_leads_created", "created_at"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    kind = Column(String(20), nullable=False)                         # demo | contact | assessment
    # Browser-generated id of one form fill: a retried POST returns the first row instead of a second lead.
    submission_id = Column(String(64), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)                         # E.164
    company = Column(String(160), nullable=True)
    message = Column(Text, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    # Assessment only: {"input": ..., "result": ..., "benchmark_version": ...} exactly as shown to the visitor.
    assessment = Column(JSON, nullable=True)

    consent_given = Column(Boolean, nullable=False, default=False)
    marketing_opt_in = Column(Boolean, nullable=False, default=False)
    notice_version = Column(String(20), nullable=True)
    notice_text_hash = Column(String(64), nullable=True)
    consent_at = Column(DateTime(timezone=True), nullable=True)
    ip_hash = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

    is_spam = Column(Boolean, nullable=False, default=False)          # honeypot filled
    # stored (not routed yet) | routed | not_configured | failed | spam
    routing_status = Column(String(20), nullable=False, default="stored")
    routing_error = Column(String(300), nullable=True)
    workspace_tenant_id = Column(String, nullable=True)
    workspace_guest_id = Column(String, nullable=True)
    workspace_inquiry_id = Column(String, nullable=True)
    notified_at = Column(DateTime(timezone=True), nullable=True)

    # Optional AI write-up of an assessment: off | pending | done | rejected | failed
    narrative = Column(Text, nullable=True)
    narrative_status = Column(String(12), nullable=True)
    narrative_prompt_version = Column(String(40), nullable=True)
