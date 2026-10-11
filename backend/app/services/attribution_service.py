"""Ad-attribution — write path (called from the WhatsApp/Instagram inbound
workers) and read path (channel breakdown) over `lead_attribution`
(HAIP_Dashboard_Metrics_Plan.md Phase 1).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.lead_attribution import LeadAttribution
from app.models.base import gen_uuid
from app.schemas.lead_attribution import ChannelAttributionResponse, ChannelAttributionRow


def record_referral_attribution(
    db: Session,
    tenant_id: str,
    conversation_id: str,
    guest_id: str,
    destination_channel: str,
    *,
    inquiry_id: Optional[str] = None,
    ad_id: Optional[str] = None,
    source_type: Optional[str] = None,
    source_url: Optional[str] = None,
    headline: Optional[str] = None,
    media_type: Optional[str] = None,
    ctwa_clid: Optional[str] = None,
    raw_referral: Optional[dict] = None,
    first_message_at: Optional[datetime] = None,
) -> Optional[LeadAttribution]:
    """
    Idempotent on (tenant_id, conversation_id) -- Meta sends the referral
    object exactly once, on a thread's first inbound message, but webhook
    retries/replays must never create a second row for the same
    conversation. Returns the existing row (unmodified) on replay, or the
    newly created row.
    """
    existing = db.query(LeadAttribution).filter_by(
        tenant_id=tenant_id, conversation_id=conversation_id,
    ).first()
    if existing:
        return existing

    row = LeadAttribution(
        id=gen_uuid(),
        tenant_id=tenant_id,
        inquiry_id=inquiry_id,
        conversation_id=conversation_id,
        guest_id=guest_id,
        destination_channel=destination_channel,
        ad_id=ad_id,
        source_type=source_type,
        source_url=source_url,
        headline=headline,
        media_type=media_type,
        ctwa_clid=ctwa_clid,
        raw_referral=raw_referral,
        first_message_at=first_message_at or datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


_STASH_TTL = 6 * 60 * 60   # a referral can only usefully wait for its first message for a few hours


def _stash_key(tenant_id: str, sender_id: str) -> str:
    return f"haip:ig_referral:{tenant_id}:{sender_id}"


def stash_referral(tenant_id: str, sender_id: str, referral: dict) -> None:
    """Hold an Instagram ad referral that arrived before its chat exists. No-op when Redis is down."""
    from app.core.cache import set_cached
    set_cached(_stash_key(tenant_id, sender_id), referral, ttl=_STASH_TTL)


def take_stashed_referral(tenant_id: str, sender_id: str) -> Optional[dict]:
    """The held referral for this sender, removed so it is used once."""
    from app.core.cache import get_cached, set_cached
    key = _stash_key(tenant_id, sender_id)
    found = get_cached(key)
    if found:
        set_cached(key, "", ttl=1)
    return found or None


def referral_fields(referral: dict) -> dict:
    """What we keep from an Instagram referral. Meta nests the ad's title under ads_context_data."""
    ctx = referral.get("ads_context_data") or {}
    return {
        "ad_id": referral.get("ad_id") or referral.get("source_id"),
        "source_type": "ad" if (referral.get("ad_id") or referral.get("source") == "ADS") else "post",
        "headline": referral.get("headline") or ctx.get("ad_title"),
        "media_type": referral.get("media_type"),
        "source_url": referral.get("source_url") or ctx.get("post_url"),
    }


def link_attribution_to_inquiry(db: Session, tenant_id: str, conversation_id: str, inquiry_id: str) -> None:
    """Backfill inquiry_id once a lead is auto-created in the same request
    the referral was captured in (the common case) -- referral rows written
    before an inquiry existed start with inquiry_id=None."""
    row = db.query(LeadAttribution).filter_by(
        tenant_id=tenant_id, conversation_id=conversation_id,
    ).first()
    if row and not row.inquiry_id:
        row.inquiry_id = inquiry_id
        db.flush()


def get_channel_attribution(db: Session, tenant_id: str, days: int = 30) -> ChannelAttributionResponse:
    """Lead count per destination channel, with distinct-ad counts -- the
    breakdown backing the Owner Daily 'leads by ad x destination' tile."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            LeadAttribution.destination_channel,
            func.count(LeadAttribution.id).label("lead_count"),
            func.count(func.distinct(LeadAttribution.ad_id)).label("ad_id_count"),
        )
        .filter(
            LeadAttribution.tenant_id == tenant_id,
            LeadAttribution.first_message_at >= since,
        )
        .group_by(LeadAttribution.destination_channel)
        .all()
    )
    channels = [
        ChannelAttributionRow(
            destination_channel=r.destination_channel,
            lead_count=r.lead_count,
            ad_id_count=r.ad_id_count,
        )
        for r in rows
    ]
    return ChannelAttributionResponse(
        period_days=days,
        total_attributed_leads=sum(c.lead_count for c in channels),
        channels=channels,
    )
