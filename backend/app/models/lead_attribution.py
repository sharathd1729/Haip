"""Ad-attribution capture for Click-to-Message leads (Dashboard Metrics Plan
Phase 1). Meta sends the `referral` object exactly once, on the first
inbound message of a thread that originated from an ad or organic post/
story -- it is never resendable, so this table is the only record of which
ad/post produced a given conversation.

Deliberately a separate table from `inquiries.source`, not more enum values
on it: one Click-to-Message ad can route to WhatsApp, Instagram Direct and
Messenger simultaneously, so destination is a property of the ad, not of
the lead. `inquiries.source` stays the coarse channel; ad-level attribution
(which ad, which destination, ROAS join to `ad_metrics` in Phase 3) lives
here.
"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class LeadAttribution(Base, TimestampMixin):
    __tablename__ = "lead_attribution"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Nullable: referral arrives on the first inbound message, before any
    # inquiry necessarily exists -- backfilled by the caller when a lead is
    # auto-created in the same request (the common case).
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False, index=True)

    # whatsapp | instagram | messenger -- the "3 destinations" axis a single
    # Click-to-Message ad can route to.
    destination_channel = Column(String(20), nullable=False, index=True)

    ad_id = Column(String(60), nullable=True, index=True)
    adset_id = Column(String(60), nullable=True)   # resolved in Phase 3 from ad_id
    campaign_id = Column(String(60), nullable=True)  # resolved in Phase 3 from ad_id

    # Captured now, unused until CAPI push is built (explicitly out of scope
    # this milestone) -- clids are sent once and can never be backfilled.
    ctwa_clid = Column(String(255), nullable=True)

    source_type = Column(String(20), nullable=True)   # ad | post
    source_url = Column(Text, nullable=True)
    headline = Column(String(500), nullable=True)
    media_type = Column(String(20), nullable=True)

    raw_referral = Column(JSON, nullable=True)  # full payload, for forensics

    first_message_at = Column(DateTime(timezone=True), nullable=False)
