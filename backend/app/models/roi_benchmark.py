"""Versioned benchmark sets for the property assessment + ROI tool (migration 145).

DOCUMENTED PLATFORM-LEVEL EXCEPTION (like platform_leads): business-level config that HAIP itself maintains for its
public website, not tenant data. No ``tenant_id`` column, no tenant policy. Written only by the owner of HAIP's sales
workspace (``POST /roi-benchmarks``, audited in that workspace's chain); read by the public assessment.

A stored version is never edited: a change is a NEW version, and activating one is a separate, audited step. Every
assessment result names the version it used, and a lead keeps the result it was shown, so changing benchmarks never
alters a report someone already received. With no active row the seed file (app/data/roi_benchmarks/) is used.
"""
from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class RoiBenchmarkVersion(Base, TimestampMixin):
    __tablename__ = "roi_benchmarks"

    id = Column(String, primary_key=True, default=gen_uuid)
    version = Column(String(40), nullable=False, unique=True)
    data = Column(JSON, nullable=False)                       # a validated schemas.assessment.BenchmarkSet
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(String, nullable=True)
