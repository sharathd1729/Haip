"""
S7 — Meta quality-rating snapshots (the table only).

GET /integrations/meta/quality and the Settings > Meta quality page read this table. The hourly poller that was meant to
fill it was removed on 20 Oct 2026: its beat entry never ran (wrong task name), it read credentials from a column nothing
writes (tenants.whatsapp_config) and would have logged the access token on an HTTP error. A future poller should read the
WhatsApp integration's encrypted credentials (see wa_health_service, which already reads quality_rating live).
"""
from app.core.database import Base
from sqlalchemy import Column, String, JSON
from app.models.base import TimestampMixin, gen_uuid



# ── Inline model ──────────────────────────────────────────────────────────────
class MetaQualitySnapshot(Base, TimestampMixin):
    __tablename__ = "meta_quality_snapshots"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    waba_id = Column(String(100), nullable=False)
    quality_rating = Column(String(20), nullable=True)   # GREEN | YELLOW | RED | UNKNOWN
    messaging_limit_tier = Column(String(50), nullable=True)
    raw = Column(JSON, nullable=True)
