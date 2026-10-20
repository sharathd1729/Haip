"""Lead workflows (migration 151): what happened to each lead, and what the playbooks did about it.

lead_journeys     one row per enquiry: the first time each milestone happened (received, assigned, notified, viewed, first
                  call attempt, first connected call, first human contact, proposal shared/delivered/read) and the outcome.
                  Milestones are written once (a guarded UPDATE ... WHERE col IS NULL) by lead_journey_tracker; the outcome
                  follows the lead's stage. A report table: everything in it can be rebuilt from the source rows.
lead_views        who opened a lead and when (first/last/count per user). The only record of "an agent saw it".
playbook_runs     one run of one playbook for one trigger (a missed call, a shared quote ...). UNIQUE(tenant, playbook,
                  trigger_ref) makes a repeated trigger a no-op. Steps fire at next_run_at (claimed with a guarded UPDATE).
playbook_actions  every action a run took or skipped (WhatsApp to the guest, task, push, staff alert), with the reason.
                  The "what fired" log on the Workflows page and the per-guest send cap read it.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class LeadJourney(Base, TimestampMixin, TenantMixin):
    __tablename__ = "lead_journeys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "inquiry_id", name="uq_lead_journeys_tenant_inquiry"),
        Index("ix_lead_journeys_tenant_received", "tenant_id", "received_at"),
        Index("ix_lead_journeys_tenant_outcome", "tenant_id", "outcome"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=False)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True, index=True)

    received_at = Column(DateTime(timezone=True), nullable=True)
    received_via = Column(String(30), nullable=True)               # the enquiry's source (META_IG, WA_DIRECT, ORGANIC_CALL ...)
    first_assigned_at = Column(DateTime(timezone=True), nullable=True)
    first_assigned_to = Column(String, nullable=True)
    first_notified_at = Column(DateTime(timezone=True), nullable=True)
    first_viewed_at = Column(DateTime(timezone=True), nullable=True)
    first_viewed_by = Column(String, nullable=True)
    first_call_attempt_at = Column(DateTime(timezone=True), nullable=True)
    first_connected_at = Column(DateTime(timezone=True), nullable=True)
    first_human_contact_at = Column(DateTime(timezone=True), nullable=True)
    first_human_contact_channel = Column(String(20), nullable=True)   # whatsapp | instagram | personal_whatsapp | call | quote
    proposal_shared_at = Column(DateTime(timezone=True), nullable=True)
    proposal_channel = Column(String(20), nullable=True)              # whatsapp | copied
    proposal_mode = Column(String(10), nullable=True)                 # sent | copied
    proposal_delivered_at = Column(DateTime(timezone=True), nullable=True)
    proposal_read_at = Column(DateTime(timezone=True), nullable=True)
    auto_messages = Column(Integer, nullable=False, default=0)        # playbook WhatsApps sent to the guest
    outcome = Column(String(10), nullable=False, default="active")   # active | won | lost | closed
    outcome_at = Column(DateTime(timezone=True), nullable=True)
    lost_reason = Column(String(30), nullable=True)
    playbooks_paused_at = Column(DateTime(timezone=True), nullable=True)
    playbooks_paused_by = Column(String, nullable=True)


class LeadView(Base, TimestampMixin, TenantMixin):
    __tablename__ = "lead_views"
    __table_args__ = (UniqueConstraint("tenant_id", "inquiry_id", "user_id", name="uq_lead_views_tenant_inquiry_user"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    first_viewed_at = Column(DateTime(timezone=True), nullable=False)
    last_viewed_at = Column(DateTime(timezone=True), nullable=False)
    views = Column(Integer, nullable=False, default=1)


class PlaybookRun(Base, TimestampMixin, TenantMixin):
    __tablename__ = "playbook_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "playbook_key", "trigger_ref", name="uq_playbook_runs_trigger"),
        Index("ix_playbook_runs_status_next", "status", "next_run_at"),
        Index("ix_playbook_runs_tenant_inquiry", "tenant_id", "inquiry_id"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    playbook_key = Column(String(40), nullable=False)
    trigger_ref = Column(String(120), nullable=False)               # "call:{call_id}", "button:{wamid}" ...
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True)
    status = Column(String(12), nullable=False, default="scheduled")  # scheduled | claimed | done | stopped | failed
    step = Column(Integer, nullable=False, default=0)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    stop_reason = Column(Text, nullable=True)
    context = Column(JSON, nullable=False, default=dict)


class PlaybookAction(Base, TimestampMixin, TenantMixin):
    __tablename__ = "playbook_actions"
    __table_args__ = (
        Index("ix_playbook_actions_tenant_guest", "tenant_id", "guest_id", "created_at"),
        Index("ix_playbook_actions_tenant_created", "tenant_id", "created_at"),
        Index("ix_playbook_actions_tenant_inquiry", "tenant_id", "inquiry_id"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("playbook_runs.id"), nullable=True)
    playbook_key = Column(String(40), nullable=False)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True)
    action = Column(String(20), nullable=False)        # wa_template | wa_text | task | push | staff_wa
    status = Column(String(12), nullable=False)        # queued | skipped | failed | done
    reason = Column(Text, nullable=True)               # why it was skipped / failed, in plain words
    message_id = Column(String, nullable=True)
    task_id = Column(String, nullable=True)
    recipient_user_id = Column(String, nullable=True)
    template_name = Column(String(100), nullable=True)
    wa_message_id = Column(String(255), nullable=True, index=True)
    acked_at = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
