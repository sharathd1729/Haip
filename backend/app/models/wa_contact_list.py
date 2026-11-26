"""A named WhatsApp contact list, e.g. "Wedding enquiries 2026" (migration 219, services/wa_contacts.py).
Membership lives on wa_subscribers.list_ids (JSON list of these ids)."""
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String, UniqueConstraint

from app.core.database import Base
from app.models.base import gen_uuid


class WaContactList(Base):
    __tablename__ = "wa_contact_lists"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_wa_contact_lists_tenant_name"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
