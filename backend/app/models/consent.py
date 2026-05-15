from sqlalchemy import Column, String, Boolean, ForeignKey
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

    guest = relationship("Guest", back_populates="consents")
