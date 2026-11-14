"""Instagram automations: what each automation did per person, and the tracked links in its DMs (migration 205)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text

from app.core.database import Base
from app.models.base import gen_uuid

# kinds written to ig_automation_events
EVENT_KINDS = ("triggered", "public_reply", "dm_sent", "dm_failed", "gate_asked", "followed", "link_sent", "clicked",
               "skipped")


class IgAutomationEvent(Base):
    __tablename__ = "ig_automation_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_id = Column(String(36), nullable=False)
    guest_id = Column(String, nullable=True)
    media_id = Column(String(64), nullable=True)
    kind = Column(String(20), nullable=False)
    detail = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class IgTrackedLink(Base):
    __tablename__ = "ig_tracked_links"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_id = Column(String(36), nullable=False)
    code = Column(String(16), nullable=False, unique=True)
    target_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
