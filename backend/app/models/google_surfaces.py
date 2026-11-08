"""Google surfaces (migration 198): what Google itself reports about the business, pulled through official APIs only.

  gbp_daily_metrics    Business Profile Performance API, one row per (location, day, metric); from the Marketing Studio
                       Google Business connection (Integration kind google_business). Deleted when it is disconnected.
  gsc_daily_totals     Search Console search analytics by date only (true totals: Google drops rare queries from
                       query-level rows). Deleted when Search Console is disconnected.
  gsc_search_rows      Search Console rows by date x query x page x country x device, capped per day
                       (google_surfaces_sync.GSC_ROWS_PER_DAY). Deleted when Search Console is disconnected.
  pagespeed_runs       PageSpeed Insights (public API, server key): real-visitor CrUX field data + lab scores per page,
                       strategy and week.
Read only through services/google_metrics.py (the shared definitions, KPI catalogue section 18).
"""

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class GbpDailyMetric(Base, TimestampMixin):
    __tablename__ = "gbp_daily_metrics"
    __table_args__ = (UniqueConstraint("tenant_id", "location", "day", "metric", name="uq_gbp_daily_metrics"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    location = Column(String(120), nullable=False)  # "locations/123"
    day = Column(Date, nullable=False)
    metric = Column(String(60), nullable=False)  # Google's DailyMetric name, e.g. WEBSITE_CLICKS
    value = Column(Integer, nullable=False, default=0)


class GscDailyTotal(Base, TimestampMixin):
    __tablename__ = "gsc_daily_totals"
    __table_args__ = (UniqueConstraint("tenant_id", "property", "day", name="uq_gsc_daily_totals"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property = Column(String(300), nullable=False)  # "sc-domain:example.com" or "https://www.example.com/"
    day = Column(Date, nullable=False)
    clicks = Column(Integer, nullable=False, default=0)
    impressions = Column(Integer, nullable=False, default=0)
    ctr = Column(Float, nullable=True)
    position = Column(Float, nullable=True)


class GscSearchRow(Base, TimestampMixin):
    __tablename__ = "gsc_search_rows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "row_key", name="uq_gsc_search_rows_key"),
        Index("ix_gsc_search_rows_tenant_property_day", "tenant_id", "property", "day"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property = Column(String(300), nullable=False)
    day = Column(Date, nullable=False)
    query = Column(String(500), nullable=False)
    page = Column(String(1000), nullable=False)
    country = Column(String(3), nullable=False)  # ISO 3166-1 alpha-3, lower case (Google's form)
    device = Column(String(10), nullable=False)  # DESKTOP | MOBILE | TABLET
    clicks = Column(Integer, nullable=False, default=0)
    impressions = Column(Integer, nullable=False, default=0)
    ctr = Column(Float, nullable=True)
    position = Column(Float, nullable=True)
    row_key = Column(String(64), nullable=False)  # sha256 of property|day|query|page|country|device


class PageSpeedRun(Base, TimestampMixin):
    __tablename__ = "pagespeed_runs"
    __table_args__ = (UniqueConstraint("tenant_id", "url", "strategy", "week_of", name="uq_pagespeed_runs"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id = Column(String, nullable=True)
    url = Column(String(1000), nullable=False)
    label = Column(String(120), nullable=True)  # "Home", or the stay's name
    strategy = Column(String(10), nullable=False)  # mobile | desktop
    week_of = Column(Date, nullable=False)  # Monday of the week measured (workspace day)
    measured_at = Column(DateTime(timezone=True), nullable=True)
    lab_performance = Column(Integer, nullable=True)  # Lighthouse performance score 0-100
    lab_lcp_ms = Column(Integer, nullable=True)
    lab_cls = Column(Float, nullable=True)
    lab_tbt_ms = Column(Integer, nullable=True)
    field_lcp_ms = Column(Integer, nullable=True)  # CrUX p75, real visitors, last 28 days
    field_inp_ms = Column(Integer, nullable=True)
    field_cls = Column(Float, nullable=True)
    field_category = Column(String(12), nullable=True)  # FAST | AVERAGE | SLOW (Google's overall verdict)
    field_is_origin = Column(Boolean, nullable=False, default=False)  # page had too few visits: whole-site data
    error = Column(String(200), nullable=True)
