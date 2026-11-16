"""WhatsApp's daily messaging limit (WhatsApp step 2): a number may start conversations with only so many unique
people per rolling 24 hours (its tier: 250, 1K, 10K, 100K or unlimited). Campaigns check what is left before each
send, so a big list waits for the next window instead of failing at Meta and hurting the number's quality.

The tier comes from the latest meta_quality_snapshots row (hourly poll). Used = unique phones a campaign reached in the
last 24 hours (an approximation: inbox templates also count at Meta).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

TIER_LIMITS = {"TIER_50": 50, "TIER_250": 250, "TIER_1K": 1000, "TIER_2K": 2000, "TIER_10K": 10000,
               "TIER_100K": 100000}


def tier_limit(db: Session, tenant_id: str) -> int | None:
    """The daily unique-recipient limit, or None when unknown or unlimited."""
    from app.workers.tasks.meta_quality_poll import MetaQualitySnapshot

    snap = (db.query(MetaQualitySnapshot).filter_by(tenant_id=tenant_id)
            .order_by(MetaQualitySnapshot.created_at.desc()).first())
    tier = (snap.messaging_limit_tier or "").upper() if snap else ""
    return TIER_LIMITS.get(tier)


def used_last_24h(db: Session, tenant_id: str, now: datetime | None = None) -> int:
    from app.models.wa_campaign_recipient import WACampaignRecipient as R

    since = (now or datetime.now(UTC)) - timedelta(hours=24)
    return db.query(func.count(func.distinct(R.phone))).filter(R.tenant_id == tenant_id, R.sent_at >= since).scalar() or 0


def remaining_today(db: Session, tenant_id: str) -> int | None:
    """How many more new people campaigns may reach now, or None for no known limit."""
    limit = tier_limit(db, tenant_id)
    return None if limit is None else max(0, limit - used_last_24h(db, tenant_id))


def next_window(db: Session, tenant_id: str) -> datetime:
    """When the oldest send of the last 24 hours ages out (at least 15 minutes from now)."""
    from app.models.wa_campaign_recipient import WACampaignRecipient as R

    now = datetime.now(UTC)
    oldest = db.query(func.min(R.sent_at)).filter(R.tenant_id == tenant_id, R.sent_at >= now - timedelta(hours=24)).scalar()
    if oldest is None:
        return now + timedelta(minutes=15)
    oldest = oldest if oldest.tzinfo else oldest.replace(tzinfo=UTC)
    return max(oldest + timedelta(hours=24, minutes=5), now + timedelta(minutes=15))
