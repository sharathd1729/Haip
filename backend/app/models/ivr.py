"""IVR call routing models."""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer,
    JSON, LargeBinary, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class IVRConfig(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ivr_configs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, unique=True)

    greeting_text = Column(String(1000), nullable=False)
    language = Column(String(10), nullable=False, default="en-IN")

    # Fernet-encrypted JSON: {username, password, server, sip_number}
    sip_credentials_enc = Column(LargeBinary, nullable=True)

    dograh_workflow_id = Column(String(255), nullable=True)
    dograh_phone_number_id = Column(String(255), nullable=True)

    business_hours_enabled = Column(Boolean, nullable=False, default=False)
    business_hours = Column(JSON, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    options = relationship(
        "IVROption",
        back_populates="ivr_config",
        cascade="all, delete-orphan",
        order_by="IVROption.digit",
    )


class IVROption(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ivr_options"
    __table_args__ = (
        UniqueConstraint("ivr_config_id", "digit", name="uq_ivr_options_config_digit"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ivr_config_id = Column(String, ForeignKey("ivr_configs.id", ondelete="CASCADE"), nullable=False)

    digit = Column(Integer, nullable=False)
    label = Column(String(100), nullable=False)
    spoken_text = Column(String(500), nullable=False)
    route_number = Column(String(20), nullable=False)
    department = Column(String(100), nullable=True)

    ivr_config = relationship("IVRConfig", back_populates="options")


class IVRCallLog(Base, TenantMixin):
    __tablename__ = "ivr_call_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    call_id = Column(String, ForeignKey("calls.id", ondelete="SET NULL"), nullable=True)
    dograh_call_id = Column(String(255), nullable=True)

    digit_pressed = Column(Integer, nullable=True)
    routed_to_department = Column(String(100), nullable=True)
    duration_seconds = Column(Integer, nullable=False, default=0)

    # SHA-256 hash of caller phone — never stored raw
    caller_phone_token = Column(String(64), nullable=True)

    called_at = Column(DateTime(timezone=True), nullable=False)
