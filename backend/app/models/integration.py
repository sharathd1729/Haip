from sqlalchemy import Column, String, Text, LargeBinary, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class IntegrationKind(str, enum.Enum):
    WHATSAPP = "whatsapp"
    CALLERDESK = "callerdesk"
    ACEFONE = "acefone"
    HOSTAWAY = "hostaway"
    INSTAGRAM = "instagram"
    RETALWISE = "retalwise"
    STAAH = "staah"
    CLOUDBEDS = "cloudbeds"


class IntegrationStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class Integration(Base, TimestampMixin, TenantMixin):
    __tablename__ = "integrations"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    kind = Column(String(50), nullable=False)        # IntegrationKind value
    status = Column(String(20), nullable=False, default="pending")

    # KMS-encrypted JSON blob of credentials (api_key, secret, tokens, etc.)
    credentials_kms_blob = Column(LargeBinary, nullable=True)

    config = Column(JSON, nullable=False, default=dict)  # phone_number_id, waba_id, webhook_url, etc.

    installed_at = Column(String, nullable=True)
    last_health_at = Column(String, nullable=True)

    tenant = relationship("Tenant", back_populates="integrations")
