"""One row per public API call made with an API key (Settings > Developers > Recent calls). Kept 30 days
(webhooks.purge_old). Written by the public API middleware after the response; a failed write is logged, never raised."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from app.core.database import Base
from app.models.base import gen_uuid


class ApiUsageLog(Base):
    __tablename__ = "api_usage_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    api_key_id = Column(String, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    method = Column(String(8), nullable=False)
    path = Column(String(200), nullable=False)                 # route template, e.g. /bookings/{booking_id}
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_api_usage_logs_key_created", "tenant_id", "api_key_id", "created_at"),)
