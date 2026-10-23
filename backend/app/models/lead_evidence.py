"""Raw evidence a person uploaded onto a lead (migration 171; lead_evidence_service).

kind     chat_export     the file WhatsApp "Export chat" makes (.txt, or .zip with _chat.txt + media); its messages are
                         written into the guest's WhatsApp thread (Message.sender_kind = "chat_export")
         call_recording  an audio file of a call made outside the IVR; it becomes a Call (ivr_provider = "upload") that goes
                         through the same transcription + analysis pipeline as an IVR recording
status   done | processing | failed   (a recording stays "processing" until its transcript and analysis are written; the
                         list reads the Call's own statuses)
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid

KINDS = ("chat_export", "call_recording")


class LeadEvidenceImport(Base, TimestampMixin, TenantMixin):
    __tablename__ = "lead_evidence_imports"
    __table_args__ = (Index("ix_lead_evidence_imports_tenant_inquiry", "tenant_id", "inquiry_id"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True, index=True)
    kind = Column(String(20), nullable=False)
    status = Column(String(12), nullable=False, default="done")
    filename = Column(String(255), nullable=True)
    uploaded_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    conversation_id = Column(String, nullable=True)
    call_id = Column(String, nullable=True)
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    duplicate_count = Column(Integer, nullable=False, default=0, server_default="0")
    media_count = Column(Integer, nullable=False, default=0, server_default="0")
    duration_seconds = Column(Integer, nullable=True)
    first_at = Column(DateTime(timezone=True), nullable=True)
    last_at = Column(DateTime(timezone=True), nullable=True)
    detail = Column(JSON, nullable=True)       # guest sender name, date order, system lines skipped, media skipped
    error = Column(Text, nullable=True)
