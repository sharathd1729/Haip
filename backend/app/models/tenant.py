from sqlalchemy import Column, String, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(50), default="growth", nullable=False)  # starter/growth/scale/enterprise
    is_active = Column(Boolean, default=True, nullable=False)
    data_region = Column(String(20), default="ap-south-1", nullable=False)

    # IVR config
    ivr_provider = Column(String(50), nullable=True)  # callerdesk / acefone
    ivr_config = Column(JSON, default=dict)

    # WhatsApp config
    whatsapp_phone_number_id = Column(String(100), nullable=True)
    whatsapp_config = Column(JSON, default=dict)

    # Brand config
    brand_name = Column(String(255), nullable=True)
    brand_config = Column(JSON, default=dict)

    # Limits (overrides plan defaults)
    monthly_call_limit = Column(String, nullable=True)
    monthly_wa_limit = Column(String, nullable=True)

    users = relationship("User", back_populates="tenant", lazy="dynamic")
    guests = relationship("Guest", back_populates="tenant", lazy="dynamic")
    properties = relationship("Property", back_populates="tenant", lazy="dynamic")
    integrations = relationship("Integration", back_populates="tenant", lazy="dynamic")
