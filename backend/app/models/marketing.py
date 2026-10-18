"""Marketing Studio tables (docs/marketing-website/PHASE0_AUDIT.md §7.3).

Measured provider data and AI assessment are stored in separate columns so they can never be confused in the UI.
A content version is immutable: an edit is a new version, and an approval is bound to one version's sha256.
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class MarketingAudit(Base, TimestampMixin):
    """A social audit: a frozen copy of the measured metrics plus the AI's reading of them."""
    __tablename__ = "marketing_audits"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    channel = Column(String(20), nullable=False, default="instagram")
    measured = Column(JSON, nullable=False)          # provider numbers, with source + captured_at; never AI-written
    assessment = Column(JSON, nullable=True)         # AuditAssessment; AI-written, labelled as such
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed
    error = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)


class MarketingPlan(Base, TimestampMixin):
    """A strategy + content calendar generated from the profile and (optionally) an audit."""
    __tablename__ = "marketing_plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    audit_id = Column(String, nullable=True)
    period_start = Column(String(10), nullable=False)    # YYYY-MM-DD
    period_end = Column(String(10), nullable=False)
    brief = Column(Text, nullable=True)
    body = Column(JSON, nullable=True)                   # MarketingPlanBody
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed | archived
    error = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)


class MarketingContent(Base, TimestampMixin):
    """One piece of content (post, carousel, story, promo) and its review state."""
    __tablename__ = "marketing_content"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    channel = Column(String(20), nullable=False, default="instagram")
    title = Column(String(160), nullable=False)
    property_id = Column(String, nullable=True)
    plan_id = Column(String, nullable=True)
    planned_for = Column(String(10), nullable=True)      # YYYY-MM-DD from the calendar; not a publish schedule
    status = Column(String(20), nullable=False, default="draft")              # schemas.marketing.ITEM_STATUSES
    current_version_id = Column(String, nullable=True)
    approved_version_id = Column(String, nullable=True)
    approved_sha256 = Column(String(64), nullable=True)
    generation_status = Column(String(20), nullable=False, default="idle")    # idle | pending | failed
    generation_error = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (Index("ix_marketing_content_tenant_status", "tenant_id", "status"),)


class MarketingContentVersion(Base):
    """Immutable. Never updated after insert."""
    __tablename__ = "marketing_content_versions"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    sha256 = Column(String(64), nullable=False)
    origin = Column(String(10), nullable=False)          # ai | human
    note = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)           # the person who wrote it, or who asked the AI for it
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("content_id", "version", name="uq_marketing_content_versions_n"),)


class MarketingApproval(Base):
    """Every review decision, bound to the exact version and hash that was seen."""
    __tablename__ = "marketing_approvals"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version_id = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False)
    decision = Column(String(20), nullable=False)        # submitted | approved | rejected | withdrawn
    note = Column(Text, nullable=True)
    actor_user_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MarketingImageJob(Base, TimestampMixin):
    """One AI image request (opt-in per tenant). On success the image becomes a media_assets row with
    source='ai' and status='pending_review': it cannot be used in content until someone with marketing.approve approves it."""
    __tablename__ = "marketing_image_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    model = Column(String(60), nullable=False)
    shape = Column(String(20), nullable=False)
    seed = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed
    error = Column(Text, nullable=True)
    asset_id = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
