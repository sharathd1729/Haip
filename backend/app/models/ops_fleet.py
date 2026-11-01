"""Ops phase 2: readiness and fleet (migration 180).

Papers (vehicle insurance/permit/FC/PUC/AIS-140, a driver's HMV licence) with expiry dates, defects, scheduled services,
onboard inventory with par levels, the automatic trip messages log and the guest ID form. Vehicles are properties; staff are
staff_profiles. Rules live in services/ops_fleet_service.py, ops_auto_messages.py and ops_guest_form.py.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
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


class OpsPaper(Base, TimestampMixin, TenantMixin):
    """One paper of a vehicle (property_id) or a person (staff_id). A newer paper of the same kind replaces the old one
    (active=False), so history stays."""

    __tablename__ = "ops_papers"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    staff_id = Column(String, ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(20), nullable=False)  # insurance | permit | fc | puc | ais140 | hmv_licence | other
    name = Column(String(120), nullable=False)
    number = Column(String(60), nullable=True)
    expires_on = Column(Date, nullable=True)
    file_key = Column(String, nullable=True)  # R2 key (media_storage.upload_ops_paper)
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (Index("ix_ops_papers_owner", "tenant_id", "property_id", "staff_id"),)


class OpsDefect(Base, TimestampMixin, TenantMixin):
    """Something wrong with a vehicle. An open critical defect blocks dispatch and keeps the vehicle off sale through a
    blocked_dates row (block_id) that is removed when the defect is closed."""

    __tablename__ = "ops_defects"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False)
    title = Column(String(200), nullable=False)
    detail = Column(Text, nullable=True)
    severity = Column(String(10), nullable=False, default="normal")  # critical | normal
    status = Column(String(10), nullable=False, default="open")  # open | closed
    source = Column(String(10), nullable=False, default="person")  # person | photo
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="SET NULL"), nullable=True)
    item_key = Column(String(40), nullable=True)  # the checklist item a staff photo flagged
    block_id = Column(String, nullable=True)  # blocked_dates.id while it keeps the vehicle off sale
    reported_by = Column(String, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(String, nullable=True)
    close_note = Column(Text, nullable=True)

    __table_args__ = (Index("ix_ops_defects_open", "tenant_id", "property_id", "status"),)


class OpsService(Base, TimestampMixin, TenantMixin):
    """A scheduled service: due by date, by odometer km, or both (whichever comes first)."""

    __tablename__ = "ops_services"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False)
    name = Column(String(120), nullable=False)
    due_on = Column(Date, nullable=True)
    due_km = Column(Integer, nullable=True)
    status = Column(String(10), nullable=False, default="open")  # open | done
    done_on = Column(Date, nullable=True)
    done_km = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    done_by = Column(String, nullable=True)


class OpsInventoryItem(Base, TimestampMixin, TenantMixin):
    """Something kept on board a vehicle, with the level it should be at (par) and the last count."""

    __tablename__ = "ops_inventory_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False)
    name = Column(String(80), nullable=False)
    par = Column(Integer, nullable=False)
    count = Column(Integer, nullable=True)
    counted_at = Column(DateTime(timezone=True), nullable=True)
    counted_by = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "property_id", "name", name="uq_ops_inventory_items_name"),)


class OpsAutoMessage(Base, TimestampMixin, TenantMixin):
    """One automatic trip message to one recipient. Unique per (file, kind, recipient): nothing is sent twice; a failed one
    is retried each hour and shown on Ops today until it goes."""

    __tablename__ = "ops_auto_messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # crew_brief | helper_chase | guest_pretrip | deposit_nudge
    recipient = Column(String(80), nullable=False)  # staff:<id> | guest | managers
    status = Column(String(10), nullable=False)  # sent | failed
    via = Column(String(10), nullable=True)  # text | template | alert
    reason = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=1)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("file_id", "kind", "recipient", name="uq_ops_auto_messages_once"),)


class OpsGuestForm(Base, TimestampMixin, TenantMixin):
    """The guest ID form of one trip. Only a SHA-256 of the link's token is stored (token = HMAC of id + nonce, so the link
    can be shown again without keeping it). data = {guests[{name, age, id_type, id_number}], emergency_name,
    emergency_phone, food, requests}; Aadhaar keeps the last 4 digits only. Erased with the guest (DPDP)."""

    __tablename__ = "ops_guest_forms"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=False)
    stay_id = Column(String, ForeignKey("stays.id", ondelete="CASCADE"), nullable=False)
    nonce = Column(String(32), nullable=False)
    token_hash = Column(String(64), nullable=False)
    data = Column(JSON, nullable=True)
    signed_name = Column(String(80), nullable=True)
    consent_version = Column(String(20), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("file_id", name="uq_ops_guest_forms_file"),
        UniqueConstraint("token_hash", name="uq_ops_guest_forms_token"),
    )
