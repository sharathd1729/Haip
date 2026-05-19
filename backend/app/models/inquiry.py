from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Numeric, Integer, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class InquiryStage(str, enum.Enum):
    NEW = "new"
    RESPONDING = "responding"
    QUOTED = "quoted"
    SITE_VISIT = "site_visit"
    BOOKED = "booked"
    LOST = "lost"
    GHOSTED = "ghosted"


class InquirySource(str, enum.Enum):
    WEBSITE = "website"
    GOOGLE = "google"
    META_IG = "meta_ig"
    META_FB = "meta_fb"
    CLICK_TO_WA = "click_to_wa"
    WA_DIRECT = "wa_direct"
    EMAIL = "email"
    PHONE = "phone"
    WALK_IN = "walk_in"
    REFERRAL = "referral"
    TRAVEL_AGENT = "travel_agent"
    OTA_AIRBNB = "ota_airbnb"
    OTA_BOOKING = "ota_booking"
    OTA_VRBO = "ota_vrbo"


class LostReason(str, enum.Enum):
    WRONG_DATES = "wrong_dates"
    WEATHER_CONCERN = "weather_concern"
    BUDGET_MISMATCH = "budget_mismatch"
    COULDNT_DECIDE = "couldnt_decide"
    CHOSE_COMPETITOR = "chose_competitor"
    NO_RESPONSE = "no_response"
    CAPACITY = "capacity"
    OTHER = "other"


class Inquiry(Base, TimestampMixin, TenantMixin):
    __tablename__ = "inquiries"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True, index=True)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    stage = Column(SAEnum(InquiryStage), default=InquiryStage.NEW, nullable=False, index=True)
    source = Column(SAEnum(InquirySource), nullable=True)
    lost_reason = Column(SAEnum(LostReason), nullable=True)
    lost_note = Column(Text, nullable=True)

    # Booking intent
    check_in = Column(String, nullable=True)   # ISO date
    check_out = Column(String, nullable=True)  # ISO date
    adults = Column(Integer, nullable=True)
    children = Column(Integer, nullable=True)
    occasion = Column(String(100), nullable=True)
    budget = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), default="INR")

    # Quote
    quoted_amount = Column(Numeric(12, 2), nullable=True)
    quoted_at = Column(String, nullable=True)
    quote_pdf_url = Column(Text, nullable=True)

    # Stage timing (K5)
    current_stage_entered_at = Column(DateTime(timezone=True), nullable=True)

    # SLA tracking
    first_response_at = Column(String, nullable=True)
    sla_breached = Column(Boolean, default=False)

    # AI
    ai_summary = Column(Text, nullable=True)
    ai_next_action = Column(Text, nullable=True)
    ai_confidence = Column(Numeric(3, 2), nullable=True)

    # Metadata
    tags = Column(JSON, default=list)
    custom_fields = Column(JSON, default=dict)

    guest = relationship("Guest", back_populates="inquiries")
    property = relationship("Property", foreign_keys=[property_id])
    assigned_user = relationship("User", foreign_keys=[assigned_to])
    conversations = relationship("Conversation", back_populates="inquiry", lazy="dynamic")
    calls = relationship("Call", back_populates="inquiry", lazy="dynamic")
