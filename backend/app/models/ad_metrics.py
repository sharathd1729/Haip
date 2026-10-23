"""Daily Meta ad performance, one row per ad per day, pulled from the Marketing API.

Unique on (tenant_id, date, ad_id) so a re-sync of the recent days (Meta restates the last few days'
figures) updates rows instead of duplicating them.
"""
from sqlalchemy import JSON, BigInteger, Column, Date, Index, Integer, Numeric, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class AdMetric(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ad_metrics"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ad_account_id = Column(String(40), nullable=False)
    date = Column(Date, nullable=False)

    campaign_id = Column(String(60), nullable=False, default="")
    campaign_name = Column(String(300), nullable=False, default="")
    adset_id = Column(String(60), nullable=False, default="")
    adset_name = Column(String(300), nullable=False, default="")
    ad_id = Column(String(60), nullable=False)
    ad_name = Column(String(300), nullable=False, default="")

    spend = Column(Numeric(14, 2), nullable=False, default=0)
    impressions = Column(BigInteger, nullable=False, default=0)
    reach = Column(BigInteger, nullable=False, default=0)
    clicks = Column(Integer, nullable=False, default=0)
    frequency = Column(Numeric(8, 3), nullable=False, default=0)
    ctr = Column(Numeric(8, 4), nullable=False, default=0)
    cpm = Column(Numeric(12, 4), nullable=False, default=0)
    conversations_started = Column(Integer, nullable=False, default=0)   # click-to-message ads
    leads = Column(Integer, nullable=False, default=0)                  # lead-form ads
    currency = Column(String(3), nullable=False, default="INR")

    link_clicks = Column(Integer, nullable=False, default=0)
    unique_clicks = Column(Integer, nullable=False, default=0)
    post_engagement = Column(Integer, nullable=False, default=0)        # reactions, comments, shares, saves
    video_views = Column(Integer, nullable=False, default=0)
    first_replies = Column(Integer, nullable=False, default=0)          # chats where the business replied
    cpc = Column(Numeric(12, 4), nullable=False, default=0)
    actions = Column(JSON, nullable=True)                                 # Meta's full action list, so no number is lost
    # Watch curve (migration 174). video_views above = 3-second views (actions[video_view]).
    video_thruplays = Column(Integer, nullable=False, default=0)        # 15 s or the whole video if shorter
    video_p25 = Column(Integer, nullable=False, default=0)
    video_p50 = Column(Integer, nullable=False, default=0)
    video_p75 = Column(Integer, nullable=False, default=0)
    video_p95 = Column(Integer, nullable=False, default=0)
    video_p100 = Column(Integer, nullable=False, default=0)
    video_avg_watch_s = Column(Numeric(10, 2), nullable=False, default=0)
    link_ctr = Column(Numeric(8, 4), nullable=False, default=0)        # inline_link_click_ctr, percent

    __table_args__ = (
        UniqueConstraint("tenant_id", "date", "ad_id", name="uq_ad_metrics_tenant_date_ad"),
        Index("ix_ad_metrics_tenant_date", "tenant_id", "date"),
        Index("ix_ad_metrics_tenant_campaign", "tenant_id", "campaign_id"),
    )
