from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Numeric, Integer, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class InquiryStage(str, enum.Enum):
    NEW = "new"
    RESPONDING = "responding"
    QUOTED = "quoted"
    SITE_VISIT = "site_visit"           # deprecated alias — kept for data compat
    SITE_VISIT_SCHEDULED = "site_visit_scheduled"   # Leads360 addition (migration 023)
    SITE_VISIT_DONE      = "site_visit_done"        # Leads360 addition (migration 023)
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
    # Leads360 additions (migration 023)
    INBOUND_CALL    = "inbound_call"
    OUTBOUND_CALL   = "outbound_call"
    OTA_MMT         = "ota_mmt"
    OTA_GOIBIBO     = "ota_goibibo"
    CHANNEL_MANAGER = "channel_manager"
    WEB_CHAT        = "web_chat"


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

    stage = Column(
        SAEnum(InquiryStage, values_callable=lambda x: [e.value for e in x]),
        default=InquiryStage.NEW, nullable=False, index=True,
    )
    source = Column(SAEnum(InquirySource, values_callable=lambda x: [e.value for e in x]), nullable=True)
    lost_reason = Column(SAEnum(LostReason, values_callable=lambda x: [e.value for e in x]), nullable=True)
    lost_note = Column(Text, nullable=True)

    # Booking intent
    check_in = Column(String, nullable=True)   # ISO date
    check_out = Column(String, nullable=True)  # ISO date
    adults = Column(Integer, nullable=True)
    children = Column(Integer, nullable=True)
    occasion  = Column(String(100), nullable=True)
    intent_tag = Column(String(30),  nullable=True, index=True)  # Phase 3: normalized bucket
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
