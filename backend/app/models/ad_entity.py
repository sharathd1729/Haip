"""Details of a campaign, ad set or ad as Meta describes it: name, status, objective, budget, dates, the ad's
creative and the ad set's audience. Refreshed on every ads sync. Insights (the numbers) live in ad_metrics.

Unique on (tenant_id, level, entity_id) so a refresh updates rows in place.
"""
from sqlalchemy import JSON, Column, DateTime, Index, Numeric, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class AdEntity(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ad_entities"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ad_account_id = Column(String(40), nullable=False)
    level = Column(String(10), nullable=False)               # campaign | adset | ad
    entity_id = Column(String(60), nullable=False)
    campaign_id = Column(String(60), nullable=False, default="")
    adset_id = Column(String(60), nullable=False, default="")
    name = Column(String(300), nullable=False, default="")

    status = Column(String(30), nullable=True)               # what the owner set: ACTIVE, PAUSED...
    effective_status = Column(String(40), nullable=True)     # what is actually happening: ACTIVE, IN_PROCESS, CAMPAIGN_PAUSED...
    objective = Column(String(60), nullable=True)            # campaigns
    optimization_goal = Column(String(60), nullable=True)    # ad sets
    daily_budget = Column(Numeric(14, 2), nullable=True)     # in the account currency, not Meta's minor units
    lifetime_budget = Column(Numeric(14, 2), nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)

    creative = Column(JSON, nullable=True)                   # ads: title, body, thumbnail_url, call_to_action_type...
    targeting = Column(JSON, nullable=True)                  # ad sets: ages, genders, locations, interests, platforms

    __table_args__ = (
        UniqueConstraint("tenant_id", "level", "entity_id", name="uq_ad_entities_tenant_level_entity"),
        Index("ix_ad_entities_tenant_level", "tenant_id", "level"),
    )
