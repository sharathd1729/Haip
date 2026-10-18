"""Before / after impact view (migration 146).

``impact_baselines``: the numbers the OWNER typed in for "before HAIP" (HAIP holds little data from before go-live), one
row per tenant and metric, each with the period it describes and where it came from. Shown as "owner-entered", never
mixed up with what HAIP measured. Every change is audited (``impact.baseline_*``).

``impact_profiles``: one row per tenant: the go-live date and the case study. The case study is a SNAPSHOT of aggregate
numbers taken when the owner clicks "Publish to case study"; the public page reads only that snapshot (no guest data,
no live query), and shows "coming soon" until one is published.
"""
from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class ImpactBaseline(Base, TimestampMixin, TenantMixin):
    __tablename__ = "impact_baselines"
    __table_args__ = (UniqueConstraint("tenant_id", "metric", name="uq_impact_baselines_tenant_metric"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    metric = Column(String(60), nullable=False)               # a key of impact_service.BASELINE_METRICS
    value = Column(Numeric(14, 2), nullable=False)
    period_label = Column(String(80), nullable=False)          # "Jan-Mar 2026, typical month" (free text, owner's words)
    source_note = Column(Text, nullable=True)                  # "from our WhatsApp export", "my estimate"
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)


class ImpactProfile(Base, TimestampMixin, TenantMixin):
    __tablename__ = "impact_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_impact_profiles_tenant"),
        UniqueConstraint("case_study_slug", name="uq_impact_profiles_slug"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    go_live_date = Column(Date, nullable=True)                 # the IST day HAIP went live
    window_days = Column(Integer, nullable=False, default=30)
    case_study_slug = Column(String(40), nullable=True)        # public URL: /case-studies/{slug}
    case_study_status = Column(String(12), nullable=False, default="draft")   # draft | published | withdrawn
    case_study_snapshot = Column(JSON, nullable=True)          # aggregates only, built by impact_service.public_snapshot
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(String, ForeignKey("users.id"), nullable=True)
