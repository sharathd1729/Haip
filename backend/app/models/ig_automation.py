"""Instagram automations: what each automation did per person, the tracked links in its DMs (migration 210), and the
questions a DM form is asking one person (migration 211)."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text

from app.core.database import Base
from app.models.base import gen_uuid

# kinds written to ig_automation_events
EVENT_KINDS = (
    "triggered",
    "public_reply",
    "dm_sent",
    "dm_failed",
    "gate_asked",
    "followed",
    "link_sent",
    "clicked",
    "skipped",
    "form_started",
    "form_completed",
    "form_dropped",
    "sequence_sent",
    "sequence_stopped",
    "opened",  # the person opened an automation DM (Instagram "seen", webhook field messaging_seen)
)

FORM_STATUSES = ("active", "completed", "handed_over", "stopped", "replaced")


class IgAutomationEvent(Base):
    __tablename__ = "ig_automation_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_id = Column(String(36), nullable=False)
    guest_id = Column(String, nullable=True)
    media_id = Column(String(64), nullable=True)
    kind = Column(String(20), nullable=False)
    detail = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class IgTrackedLink(Base):
    __tablename__ = "ig_tracked_links"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_id = Column(String(36), nullable=False)
    code = Column(String(16), nullable=False, unique=True)
    target_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class IgFormSession(Base):
    """One person answering one automation's questions in the DM (services/ig_dm_form.py). While a row is active and not
    expired, that person's messages are answers: the AI concierge and keyword rules stay out of the chat."""

    __tablename__ = "ig_form_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    rule_id = Column(String(36), nullable=False)
    guest_id = Column(String, nullable=False)
    conversation_id = Column(String, nullable=True)
    recipient_id = Column(String(64), nullable=False)   # Instagram-scoped id the questions go to
    step = Column(Integer, nullable=False, default=0)   # index into the rule's form.questions
    answers = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="active")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC))
