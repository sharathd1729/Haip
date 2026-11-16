"""Meta's per-message pricing from WhatsApp status webhooks (migration 213, services/wa_costs.py)."""
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint

from app.core.database import Base
from app.models.base import gen_uuid


class WaPricingEvent(Base):
    __tablename__ = "wa_pricing_events"
    __table_args__ = (UniqueConstraint("tenant_id", "wamid", name="uq_wa_pricing_events_wamid"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    wamid = Column(String(255), nullable=False)
    category = Column(String(40), nullable=True)      # marketing | utility | authentication | service | referral_conversion
    billable = Column(Boolean, nullable=False, default=True)
    pricing_model = Column(String(20), nullable=True)  # PMP (per message) | CBP (older conversation pricing)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
