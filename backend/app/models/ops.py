"""Operations module tables (migration 178).

Staff are NOT guests. A phone number on an active StaffProfile is routed to the ops handler on inbound WhatsApp and never
reaches identity resolution, leads, the inbox or the concierge (workers/tasks/whatsapp.py).

Who gets an alert is decided only by roster_service.recipients_for_step (shift patterns + overrides + escalation chains).
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class StaffProfile(Base, TimestampMixin, TenantMixin):
    """An on-ground staff member. May have no HAIP login (user_id NULL): they act through WhatsApp buttons."""

    __tablename__ = "staff_profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    name = Column(String(120), nullable=False)
    phone_e164 = Column(String(20), nullable=False)
    languages = Column(JSON, default=list)
    whatsapp_opt_in_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "phone_e164", name="uq_staff_profiles_phone"),)


class StaffDuty(Base, TimestampMixin, TenantMixin):
    __tablename__ = "staff_duties"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    staff_id = Column(
        String,
        ForeignKey("staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    duty = Column(String(30), nullable=False)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)  # NULL = every property


class ShiftPattern(Base, TimestampMixin, TenantMixin):
    """Weekly repeating shift. Minutes are local (tenant timezone). end_minute <= start_minute = crosses midnight."""

    __tablename__ = "shift_patterns"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    staff_id = Column(
        String,
        ForeignKey("staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    duty = Column(String(30), nullable=False)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    weekday = Column(Integer, nullable=False)  # 0 = Monday
    start_minute = Column(Integer, nullable=False)  # 0..1439
    end_minute = Column(Integer, nullable=False)  # 1..1440
    active = Column(Boolean, nullable=False, default=True)


class ShiftOverride(Base, TimestampMixin, TenantMixin):
    """leave = off in the window; swap = off, replacement covers their duties; extra = on duty in the window."""

    __tablename__ = "shift_overrides"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    staff_id = Column(
        String,
        ForeignKey("staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(10), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    duty = Column(String(30), nullable=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    replacement_staff_id = Column(String, ForeignKey("staff_profiles.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)


class EscalationChain(Base, TimestampMixin, TenantMixin):
    __tablename__ = "escalation_chains"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    duty = Column(String(30), nullable=False)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    steps = Column(JSON, nullable=False)


class OpsSettings(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ops_settings"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, unique=True)
    alerts_enabled = Column(Boolean, nullable=False, default=True)
    sla = Column(JSON, nullable=True)
    quiet_hours = Column(JSON, nullable=True)
    templates = Column(JSON, nullable=True)
    template_language = Column(String(10), nullable=False, default="en")


class OpsItem(Base, TimestampMixin, TenantMixin):
    """Something that needs a person: an incident, an unpaid balance at check-out, an overdue checklist."""

    __tablename__ = "ops_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    category = Column(String(30), nullable=True)
    severity = Column(String(10), nullable=False)
    duty = Column(String(30), nullable=False)
    status = Column(String(15), nullable=False, default="open")
    source = Column(String(20), nullable=False, default="staff")  # staff | guest_chat | system | manager

    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    stay_id = Column(String, ForeignKey("stays.id"), nullable=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True)
    conversation_id = Column(String, nullable=True)
    service_request_id = Column(String, nullable=True)

    current_step = Column(Integer, nullable=False, default=0)
    dispatched_step = Column(Integer, nullable=True)  # last step actually alerted
    dispatch_after = Column(DateTime(timezone=True), nullable=True)  # quiet hours: hold the first alert until then
    step_started_at = Column(DateTime(timezone=True), nullable=True)
    ack_due_at = Column(DateTime(timezone=True), nullable=True)
    resolve_due_at = Column(DateTime(timezone=True), nullable=True)
    resolve_breached_at = Column(DateTime(timezone=True), nullable=True)
    repeat_count = Column(Integer, nullable=False, default=0)  # re-alerts after the chain ran out
    escalation_exhausted = Column(Boolean, nullable=False, default=False)

    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by_staff_id = Column(String, nullable=True)
    acknowledged_by_user_id = Column(String, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_staff_id = Column(String, nullable=True)
    resolved_by_user_id = Column(String, nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (Index("ix_ops_items_open", "tenant_id", "status"),)


class OpsEscalationEvent(Base, TenantMixin):
    __tablename__ = "ops_escalation_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    item_id = Column(
        String,
        ForeignKey("ops_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event = Column(String(30), nullable=False)
    step = Column(Integer, nullable=True)
    actor_staff_id = Column(String, nullable=True)
    actor_user_id = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class OpsAlertSend(Base, TimestampMixin, TenantMixin):
    """One alert to one recipient for one step. The quick-reply payload carries this row's id + nonce."""

    __tablename__ = "ops_alert_sends"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    item_id = Column(
        String,
        ForeignKey("ops_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step = Column(Integer, nullable=False)
    staff_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    phone_e164 = Column(String(20), nullable=True)
    channel = Column(String(10), nullable=False)  # whatsapp | push
    template = Column(String(80), nullable=True)
    wamid = Column(String(128), nullable=True, unique=True)
    status = Column(String(12), nullable=False, default="queued")  # queued|sent|delivered|read|failed|skipped
    error = Column(Text, nullable=True)
    nonce = Column(String(32), nullable=True)
    response = Column(String(12), nullable=True)  # ack | decline
