"""A tracked click-to-chat WhatsApp link with its QR code and website button (migration 214, services/wa_entry_links.py)."""
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base
from app.models.base import gen_uuid


class WaEntryLink(Base):
    __tablename__ = "wa_entry_links"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    code = Column(String(16), nullable=False, unique=True)
    name = Column(String(80), nullable=False)
    prefill_text = Column(String(500), nullable=False, default="")
    phone = Column(String(20), nullable=False)          # digits only, with country code (wa.me format)
    clicks = Column(Integer, nullable=False, default=0)
    chats = Column(Integer, nullable=False, default=0)
    last_clicked_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
