from sqlalchemy import Column, String, Boolean, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class Consent(Base, TimestampMixin, TenantMixin):
    __tablename__ = "consents"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False, index=True)

    channel = Column(String(50), nullable=False)    # whatsapp | ivr | web_form
    scope = Column(String(50), nullable=False)      # recording | marketing | profiling
    granted = Column(Boolean, nullable=False)

    source = Column(String(50), nullable=True)      # ivr_prompt | wa_optin | web_form
    recorded_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=True)

    # D3: Consent proof fields (DPDP §7 — proof of collection)
    proof_ip = Column(String(64), nullable=True)            # IP at time of consent
    proof_user_agent = Column(Text, nullable=True)          # Browser UA
    proof_source = Column(String(255), nullable=True)       # URL/surface where captured
    notice_version = Column(String(20), nullable=True)      # e.g. "en-v2"
    notice_text_hash = Column(String(64), nullable=True)    # sha256 of shown notice
    consent_payload = Column(JSON, nullable=True)           # Full checkbox state snapshot

    # D1: withdrawal tracking
    withdrawn_at = Column(String, nullable=True)
    withdrawal_reason = Column(String(100), nullable=True)  # user_keyword | user_form | admin

    guest = relationship("Guest", back_populates="consents")
