"""
Insight model — AI-generated proactive alerts surfaced in the right-rail
Insights Panel and the Executive Dashboard.

Each row represents one active (or recently dismissed) insight for a tenant.
Detectors upsert by (tenant_id, category_code, target_id) so the same
condition never produces duplicate rows.
"""

import enum
from sqlalchemy import Column, String, Text, Boolean, Integer, JSON, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class InsightSeverity(str, enum.Enum):
    CRITICAL = "critical"   # 5 — red
    HIGH     = "high"       # 4 — red/orange
    MEDIUM   = "medium"     # 3 — amber
    LOW      = "low"        # 2 — blue/teal
    INFO     = "info"       # 1 — gray


class InsightCategory(str, enum.Enum):
    # A — Urgency
    URGENCY     = "urgency"
    # B — Occupancy
    OCCUPANCY   = "occupancy"
    # C — Revenue
    REVENUE     = "revenue"
    # D — Quality/Compliance
    QUALITY     = "quality"


class Insight(Base, TimestampMixin, TenantMixin):
    __tablename__ = "insights"

    id          = Column(String, primary_key=True, default=gen_uuid)
    tenant_id   = Column(String, nullable=False, index=True)

    # Detector identity — used for idempotent upsert
    category_code = Column(String(10), nullable=False, index=True)   # "A1", "B2", etc.
    target_id     = Column(String, nullable=True)                     # property_id / agent_id / None

    # Display
    category    = Column(String(20), nullable=False)                  # InsightCategory value
    severity    = Column(String(10), nullable=False, default="medium") # InsightSeverity value
    title       = Column(String(255), nullable=False)
    body        = Column(Text, nullable=True)
    cta_label   = Column(String(100), nullable=True)
    cta_href    = Column(String(500), nullable=True)

    # State
    is_dismissed      = Column(Boolean, default=False, nullable=False, index=True)
    dismissed_by      = Column(String, nullable=True)                 # user_id
    dismissed_at      = Column(DateTime(timezone=True), nullable=True)
    is_auto_resolved  = Column(Boolean, default=False, nullable=False)
    auto_resolved_at  = Column(DateTime(timezone=True), nullable=True)

    # Raw data snapshot that triggered the insight (for debugging / audit)
    data_snapshot = Column(JSON, nullable=True)

    # TTL: insight expires at this time (detector re-creates if still relevant)
    expires_at = Column(DateTime(timezone=True), nullable=True)
