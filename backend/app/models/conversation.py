from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid
import enum


class ChannelType(str, enum.Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    VOICE = "voice"
    WEBCHAT = "webchat"
    EMAIL = "email"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageDeliveryState(str, enum.Enum):
    """
    Lifecycle of an outbound message send (orthogonal to was_approved).

    pending   — row inserted, not yet enqueued
    queued    — Celery task has been dispatched
    sent      — Meta Cloud API returned 200 with a wamid
    delivered — Meta status webhook: delivered
    read      — Meta status webhook: read
    failed    — retry exhaustion or permanent 4xx from Meta
    rejected  — Meta returned an explicit error code (e.g. template rejected)
    """
    PENDING   = "pending"
    QUEUED    = "queued"
    SENT      = "sent"
    DELIVERED = "delivered"
    READ      = "read"
    FAILED    = "failed"
    REJECTED  = "rejected"


class Conversation(Base, TimestampMixin, TenantMixin):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)

    channel = Column(SAEnum(ChannelType), nullable=False, index=True)
    channel_conversation_id = Column(String(255), nullable=True, index=True)  # WA thread ID etc.
    is_open = Column(Boolean, default=True, nullable=False, index=True)

    # SLA
    first_response_at = Column(String, nullable=True)
    last_message_at = Column(String, nullable=True)
    sla_breached = Column(Boolean, default=False)

    # AI Concierge
    ai_mode = Column(String(20), default="shadow")  # shadow / autonomous / off
    ai_draft = Column(Text, nullable=True)           # Pending AI reply

    guest = relationship("Guest")
    inquiry = relationship("Inquiry", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", lazy="dynamic", order_by="Message.created_at")


class Message(Base, TimestampMixin, TenantMixin):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)

    direction = Column(SAEnum(MessageDirection), nullable=False)
    channel = Column(SAEnum(ChannelType), nullable=False)

    # Content
    body = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)
    media_type = Column(String(50), nullable=True)  # image/audio/video/document

    # Channel metadata
    channel_message_id = Column(String(255), nullable=True, index=True)
    channel_status = Column(String(50), nullable=True)  # sent/delivered/read/failed

    # AI
    is_ai_generated = Column(Boolean, default=False)
    ai_confidence = Column(String(10), nullable=True)
    was_approved = Column(Boolean, nullable=True)  # null = not AI, True/False = approved/rejected

    # Idempotency — prevents duplicate sends on network retry
    # Partial unique index (tenant_id, idempotency_key WHERE NOT NULL) added in migration 005
    idempotency_key = Column(String(64), nullable=True, index=False)

    # Delivery state — tracks the outbound send lifecycle independently of approval
    # NULL for inbound messages; defaults to 'pending' for outbound (migration 006)
    delivery_state = Column(
        SAEnum(MessageDeliveryState), nullable=True,
        default=None,  # set explicitly in send_message endpoint
    )
    delivery_error = Column(Text, nullable=True)  # last error from Meta API

    # Sender
    sender_id = Column(String, ForeignKey("users.id"), nullable=True)
    sender_name = Column(String(255), nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
