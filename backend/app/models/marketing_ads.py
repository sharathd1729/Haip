"""Performance marketer tables (agency M5): ad drafts, boost rules, Conversions API events.

An ad draft points at one APPROVED content version (and its sha), so the ad shows exactly what the owner approved.
Nothing reaches Meta until a draft is approved by a person, or made by a boost rule a person approved, and fits the
workspace's monthly cap. Meta ids are saved one step at a time, so a retry resumes and never creates a second ad.
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class MarketingAdDraft(Base, TimestampMixin):
    __tablename__ = "marketing_ad_drafts"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version_id = Column(String, nullable=False)                    # the approved version the ad shows
    content_sha = Column(String(64), nullable=False)
    origin = Column(String(10), nullable=False, default="manual")  # manual | rule
    rule_id = Column(String, ForeignKey("marketing_boost_rules.id"), nullable=True, index=True)
    window_key = Column(String(40), nullable=True)                 # the weekend a rule boost is for, e.g. "weekend:2026-11-13"
    destination = Column(String(20), nullable=False)               # whatsapp | instagram
    daily_budget_inr = Column(Integer, nullable=False)
    days = Column(Integer, nullable=False)
    spend_cap_inr = Column(Integer, nullable=False)                # Meta campaign spend_cap; never more than daily x days
    audience = Column(JSON, nullable=False)
    # draft | approved | pushing | live | paused | ended | failed | cancelled
    status = Column(String(20), nullable=False, default="draft")
    created_by = Column(String, nullable=True)                     # NULL for rule-made drafts (payload.actor in audit)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_note = Column(String(300), nullable=True)
    meta = Column(JSON, nullable=True)                             # image_hash / video_id / campaign / adset / creative / ad ids
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    spent_inr = Column(Numeric(14, 2), nullable=True)              # from the daily Meta sync
    tries = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "rule_id", "window_key", name="uq_marketing_ad_drafts_rule_window"),)


class MarketingBoostRule(Base, TimestampMixin):
    """'If a weekend is under 50% booked 10 days out, boost the latest reel, max Rs 3,000'. Approved once: the
    approval binds to the rule body's sha, and any edit puts it back to draft."""
    __tablename__ = "marketing_boost_rules"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    body = Column(JSON, nullable=False)                            # {condition, action} (schemas/marketing_ads.py)
    body_sha = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="draft")   # draft | approved | paused
    created_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_sha = Column(String(64), nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_result = Column(JSON, nullable=True)                      # what the last check saw and did


class MarketingCapiEvent(Base, TimestampMixin):
    """One event sent (or deliberately not sent) to Meta: a booking as Purchase (stay_id, unique per stay), or since
    studio plan phase 5 a click-to-WhatsApp lead as LeadSubmitted / QualifiedLead (inquiry_id, unique per enquiry and
    event, migration 177). Never sent twice."""
    __tablename__ = "marketing_capi_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    stay_id = Column(String, nullable=True)
    inquiry_id = Column(String, nullable=True)
    event_name = Column(String(40), nullable=False, default="Purchase")
    event_id = Column(String(80), nullable=False)                  # Meta's dedup key
    value = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="INR")
    action_source = Column(String(30), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending | sent | skipped | failed
    reason = Column(String(300), nullable=True)                   # why skipped / the last error
    tries = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    fbtrace_id = Column(String(80), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "stay_id", "event_name", name="uq_marketing_capi_events_stay"),
                      UniqueConstraint("tenant_id", "inquiry_id", "event_name", name="uq_marketing_capi_events_inquiry"))
