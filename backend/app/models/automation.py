"""Automation rules and run-log models."""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Integer, JSON, DateTime, ForeignKey, Text
from app.core.database import Base


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id             = Column(String(36), primary_key=True)
    tenant_id      = Column(String(36), nullable=False, index=True)
    name           = Column(String(255), nullable=False)
    description    = Column(String(500), nullable=True)
    trigger        = Column(String(100), nullable=False)
    trigger_config = Column(JSON, default=dict)   # {"delay_hours": 2} for timer triggers
    action         = Column(String(100), nullable=False)
    action_config  = Column(JSON, default=dict)   # {"template_id": "...", "channel": "whatsapp"}
    is_active      = Column(Boolean, nullable=False, default=True)
    run_count      = Column(Integer, nullable=False, default=0)
    last_run_at    = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                            onupdate=lambda: datetime.now(timezone.utc))


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id              = Column(String(36), primary_key=True)
    tenant_id       = Column(String(36), nullable=False, index=True)
    automation_id   = Column(String(36), ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_name = Column(String(255), nullable=True)   # cached for list display
    status          = Column(String(20), nullable=False)   # success | failed | skipped
    trigger_event   = Column(String(100), nullable=True)
    context         = Column(JSON, default=dict)           # {inquiry_id, call_id, guest_id, ...}
    detail          = Column(String(500), nullable=True)   # human-readable outcome
    error           = Column(Text, nullable=True)          # stack trace on failure
    ran_at          = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
