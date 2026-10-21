"""Website builder tables (migration 158, docs/website-builder/README.md).

A site's content lives in one JSON document per version. Only the head draft is ever rewritten (autosave); once a
version is submitted it is frozen, and an approval is bound to its sha256. Booking settings (mode, deposit) are
operational, not content, so they live on the site row and change through an audited owner/manager endpoint.
"""
from sqlalchemy import (JSON, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
                        UniqueConstraint)

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Site(Base, TimestampMixin):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("slug", name="uq_sites_slug"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    slug = Column(String(63), nullable=False)                      # the free subdomain label, globally unique
    status = Column(String(20), nullable=False, default="draft")   # draft | live | paused
    settings = Column(JSON, nullable=True)                          # schemas.website.SiteSettings
    draft_version_id = Column(String, nullable=True)
    live_version_id = Column(String, nullable=True)
    created_by = Column(String, nullable=True)


class SiteVersion(Base, TimestampMixin):
    __tablename__ = "site_versions"
    __table_args__ = (UniqueConstraint("site_id", "number", name="uq_site_versions_number"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    doc = Column(JSON, nullable=False)
    sha256 = Column(String(64), nullable=False)
    # draft | in_review | approved | published | superseded | rejected | withdrawn
    status = Column(String(20), nullable=False, default="draft")
    origin = Column(String(10), nullable=False, default="human")    # human | ai | restore | seed
    note = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    submitted_by = Column(String, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(String, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)


class SiteDomain(Base, TimestampMixin):
    __tablename__ = "site_domains"
    __table_args__ = (UniqueConstraint("hostname", name="uq_site_domains_hostname"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False, index=True)
    hostname = Column(String(253), nullable=False)                 # lower-case, no port, no trailing dot
    kind = Column(String(12), nullable=False, default="custom")     # subdomain | custom
    status = Column(String(20), nullable=False, default="pending")  # pending | verified | active | failed | removed
    verify_token = Column(String(64), nullable=False)
    provider_ref = Column(String(120), nullable=True)               # Cloudflare custom-hostname id, when used
    error = Column(Text, nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)


class BookingHold(Base, TimestampMixin):
    """Dates a website guest is paying for. While status is 'held' (and not expired) the website treats the dates as
    taken; staff bookings do not see holds, so the confirm step re-checks under a lock and raises a task on a clash."""
    __tablename__ = "booking_holds"
    __table_args__ = (Index("ix_booking_holds_tenant_property_status", "tenant_id", "property_id", "status"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False)
    property_id = Column(String, nullable=False)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    adults = Column(Integer, nullable=False, default=1)
    children = Column(Integer, nullable=False, default=0)
    mode = Column(String(12), nullable=False)                        # instant | deposit | request
    # held | requested | confirming | confirmed | expired | released | paid_conflict | failed
    status = Column(String(20), nullable=False, default="held")
    quote = Column(JSON, nullable=False)                             # the server-priced quote, frozen
    total = Column(Numeric(12, 2), nullable=False)                   # rupees, GST included
    pay_now = Column(Numeric(12, 2), nullable=False, default=0)
    gst_percent = Column(Numeric(5, 2), nullable=True)               # NULL when the nights straddle two GST slabs
    guest_details = Column(JSON, nullable=True)                      # name, email, note, gstin, company, arrival
    session_hash = Column(String(64), nullable=False)                # sha256 of the browser's session token
    expires_at = Column(DateTime(timezone=True), nullable=False)
    guest_id = Column(String, nullable=True)
    inquiry_id = Column(String, nullable=True)
    stay_id = Column(String, nullable=True)
    payment_link_id = Column(String(64), nullable=True, index=True)  # Razorpay plink_xxx
    payment_url = Column(Text, nullable=True)
    payment_id = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)


class GuestAccessToken(Base, TimestampMixin):
    __tablename__ = "guest_access_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_guest_access_tokens_hash"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    stay_id = Column(String, nullable=False, index=True)
    token_hash = Column(String(64), nullable=False)
    purpose = Column(String(20), nullable=False, default="manage")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


class SiteAiJob(Base, TimestampMixin):
    __tablename__ = "site_ai_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)                        # generate | edit
    request = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")   # pending | running | ready | failed
    result = Column(JSON, nullable=True)                              # {reply, changes[], refused[]}
    error = Column(Text, nullable=True)
    base_version_id = Column(String, nullable=True)
    result_version_id = Column(String, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)


class SitePageView(Base, TimestampMixin):
    __tablename__ = "site_page_views"
    __table_args__ = (UniqueConstraint("site_id", "day", "path", "source", name="uq_site_page_views_key"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, ForeignKey("sites.id"), nullable=False)
    day = Column(String(10), nullable=False)
    path = Column(String(200), nullable=False)
    source = Column(String(60), nullable=False, default="direct")
    views = Column(Integer, nullable=False, default=0)
