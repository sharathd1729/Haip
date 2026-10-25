"""Ops files, jobs and checklists, trip money (migration 179).

One OpsFile per booking (stay). A pack (services/ops_pack_catalog.py) names its steps and seeds its checklists. Work is an
OpsJob with OpsJobItem rows (one per checklist line); staff fill them by WhatsApp photo, a manager can set them by hand.
Money the guest pays still lives on the booking (stays, stay_addons, stay_payments, stay_deposits): an approved OpsExtra and
the extra distance become stay_addons rows, so invoices and the bookings page see them without a second ledger.
"""
from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint,
)

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class OpsFile(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ops_files"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False)
    pack = Column(String(30), nullable=False)
    state = Column(String(20), nullable=False)                 # pack state machine; caravan: handed_over .. closed, cancelled
    details = Column(JSON, nullable=False, default=dict)       # typed per pack (schemas/ops_files.py)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by = Column(String, nullable=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    dispatched_by = Column(String, nullable=True)
    returned_at = Column(DateTime(timezone=True), nullable=True)
    return_checked_at = Column(DateTime(timezone=True), nullable=True)
    return_checked_by = Column(String, nullable=True)
    report_approved_at = Column(DateTime(timezone=True), nullable=True)
    report_approved_by = Column(String, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("stay_id", name="uq_ops_files_stay"),
        Index("ix_ops_files_tenant_state", "tenant_id", "state"),
    )


class OpsFileEvent(Base, TenantMixin):
    """The file's timeline, append-only. auto = written by the system, not a person."""
    __tablename__ = "ops_file_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=False, index=True)
    at = Column(DateTime(timezone=True), nullable=False)
    text = Column(Text, nullable=False)
    auto = Column(Boolean, nullable=False, default=False)
    actor_id = Column(String, nullable=True)


class OpsChecklistTemplate(Base, TimestampMixin, TenantMixin):
    """A business's own checklist for one pack + kind, seeded from the pack's defaults. items = [{key, label, critical,
    source (staff | system | manager), photo}]. Editing the words never changes jobs already opened."""
    __tablename__ = "ops_checklist_templates"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    pack = Column(String(30), nullable=False)
    kind = Column(String(20), nullable=False)                  # readiness | handover | return | turnover
    name = Column(String(120), nullable=False)
    items = Column(JSON, nullable=False, default=list)
    active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "pack", "kind", name="uq_ops_checklist_templates_kind"),)


class OpsJob(Base, TimestampMixin, TenantMixin):
    """One piece of work with a checklist. file_id is NULL for work between bookings (a turnover, a room job)."""
    __tablename__ = "ops_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    kind = Column(String(20), nullable=False)
    template_id = Column(String, nullable=True)
    staff_id = Column(String, ForeignKey("staff_profiles.id"), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(12), nullable=False, default="open")    # open | done | cancelled
    completed_at = Column(DateTime(timezone=True), nullable=True)


class OpsJobItem(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ops_job_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    job_id = Column(String, ForeignKey("ops_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(40), nullable=False)
    label = Column(String(200), nullable=False)
    critical = Column(Boolean, nullable=False, default=False)
    source = Column(String(10), nullable=False, default="staff")   # staff | system | manager
    photo_required = Column(Boolean, nullable=False, default=False)
    status = Column(String(10), nullable=False, default="pending") # pending | green | red
    note = Column(Text, nullable=True)
    photo_key = Column(String, nullable=True)                      # R2 key of the staff photo
    ai_verdict = Column(JSON, nullable=True)                       # {ok, reason, model} from the photo check
    set_by_user_id = Column(String, nullable=True)
    set_by_staff_id = Column(String, nullable=True)
    set_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("job_id", "key", name="uq_ops_job_items_key"),)


class OpsExpense(Base, TimestampMixin, TenantMixin):
    """Money spent on a booking or a unit. bill_key (vendor|date|amount) is unique per business so a bill sent twice is
    refused; typed expenses without a bill have no key."""
    __tablename__ = "ops_expenses"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    category = Column(String(20), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)                # GST included
    gst_amount = Column(Numeric(12, 2), nullable=True)
    vendor = Column(String(120), nullable=True)
    bill_date = Column(Date, nullable=True)
    note = Column(Text, nullable=True)
    source = Column(String(10), nullable=False, default="manual")  # photo | manual
    photo_key = Column(String, nullable=True)
    bill_key = Column(String(200), nullable=True)
    staff_id = Column(String, nullable=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "bill_key", name="uq_ops_expenses_bill"),)


class OpsExtra(Base, TimestampMixin, TenantMixin):
    """Something the guest asked for during the booking, waiting for a manager. Approval writes a stay_addons row."""
    __tablename__ = "ops_extras"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    label = Column(String(200), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)                # GST included
    status = Column(String(10), nullable=False, default="proposed")  # proposed | approved | removed
    stay_addon_id = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
