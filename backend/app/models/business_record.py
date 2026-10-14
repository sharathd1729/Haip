"""Structured, versioned business records (packages, destinations, itineraries, commercial policies).

One row per VERSION. A published version is never edited: a change is a new version, a rollback publishes a copy of an older one.
Guest-facing code reads only `published` rows whose effective window contains the date (business_data_service.get_effective);
drafts, rejected, superseded-and-ended and inactive rows are invisible to it. See docs/ai/RATHA_KB_EVOLUTION.md.
"""
from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class BusinessRecord(Base, TimestampMixin, TenantMixin):
    __tablename__ = "business_records"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    kind = Column(String(30), nullable=False)             # see app.schemas.business_data.KINDS
    key = Column(String(60), nullable=False)              # stable slug within tenant + kind
    version = Column(Integer, nullable=False)             # per (tenant, kind, key), from 1
    status = Column(String(20), nullable=False, default="draft")   # draft | published | superseded | rejected | inactive

    data = Column(JSON, nullable=False)                   # validated by KIND_MODELS[kind] on every write
    effective_from = Column(Date, nullable=True)          # set when published (a future date schedules the change)
    effective_to = Column(Date, nullable=True)            # set when a later version takes over, or on deactivation

    change_note = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    published_by = Column(String, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    rejected_by = Column(String, nullable=True)
    rejected_reason = Column(Text, nullable=True)
    supersedes_id = Column(String, nullable=True)         # the version this one replaced when published
    rollback_of_id = Column(String, nullable=True)        # set on a draft created by rolling back to an older version

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "key", "version", name="uq_business_records_version"),
        Index("ix_business_records_lookup", "tenant_id", "kind", "key", "status"),
    )
