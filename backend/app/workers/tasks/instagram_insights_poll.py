"""
Organic Instagram insights -- daily snapshot: account overview, engagement
totals, audience demographics, and per-post performance.

Same shape as meta_quality_poll.py (inline models, avoid a new Alembic
migration for a small polling feature -- established precedent in this
codebase, see messaging.py's own inline-models docstring). Every metric
below was confirmed live against Ratha's real connected account before
being wired in -- see meta_graph.py's adapter methods for what was
verified and what's genuinely provider behavior that could vary by
account (e.g. the demographics minimum-audience threshold).
"""
import uuid
import httpx
import structlog
from celery import shared_task
from sqlalchemy import Column, String, JSON, Integer, Text

from app.core.database import SessionLocal, Base
from app.core.encryption import decrypt_credentials
from app.models.base import TimestampMixin, gen_uuid
from app.models.integration import Integration

log = structlog.get_logger()

_DAILY_METRICS = ["reach", "profile_views", "follower_count"]
_ENGAGEMENT_METRICS = [
    "accounts_engaged", "total_interactions", "likes", "comments",
    "shares", "saves", "replies", "profile_links_taps",
]
_DEMOGRAPHIC_BREAKDOWNS = ["city", "country", "age", "gender"]
_MEDIA_INSIGHT_METRICS = ["reach", "saved", "shares", "total_interactions"]
_RECENT_MEDIA_LIMIT = 12


class InstagramInsightsSnapshot(Base, TimestampMixin):
    __tablename__ = "instagram_insights_snapshots"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ig_account_id = Column(String(100), nullable=False)

    # Daily time-series
    reach = Column(Integer, nullable=True)
    profile_views = Column(Integer, nullable=True)
    follower_count = Column(Integer, nullable=True)

    # Account overview (plain object fields, not /insights)
    followers_count = Column(Integer, nullable=True)
    following_count = Column(Integer, nullable=True)
    media_count = Column(Integer, nullable=True)

    # Engagement totals (metric_type=total_value)
    accounts_engaged = Column(Integer, nullable=True)
    total_interactions = Column(Integer, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    saves = Column(Integer, nullable=True)
    replies = Column(Integer, nullable=True)
    profile_links_taps = Column(Integer, nullable=True)

    # Audience demographics -- {"city": [...], "country": [...], "age": [...], "gender": [...]}
    demographics = Column(JSON, nullable=True)

    raw = Column(JSON, nullable=True)


class InstagramPostSnapshot(Base, TimestampMixin):
    """One row per post, refreshed in place on every poll (not appended) --
    engagement numbers change over a post's lifetime, and this table only
    needs to answer "how is each of our recent posts doing right now", not
    a historical trend per post."""
    __tablename__ = "instagram_post_snapshots"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    media_id = Column(String(100), nullable=False, index=True)
    caption = Column(Text, nullable=True)
    media_type = Column(String(20), nullable=True)
    permalink = Column(Text, nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    posted_at = Column(String(50), nullable=True)
    like_count = Column(Integer, nullable=True)
    comments_count = Column(Integer, nullable=True)
    reach = Column(Integer, nullable=True)
    saved = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    total_interactions = Column(Integer, nullable=True)


@shared_task(name="instagram_insights.poll_all_tenants")
def poll_all_tenants():
    db = SessionLocal()
    try:
        integrations = db.query(Integration).filter_by(kind="instagram", status="active").all()
        for integ in integrations:
            try:
                _poll_tenant(db, integ)
            except Exception as exc:
                log.error("instagram_insights_poll_failed", tenant_id=integ.tenant_id, error=str(exc))
        db.commit()
        log.info("instagram_insights_polled", tenants=len(integrations))
        return {"tenants_polled": len(integrations)}
    finally:
        db.close()


def _poll_tenant(db, integ: Integration) -> None:
    if not integ.credentials_kms_blob:
        return
    creds = decrypt_credentials(integ.credentials_kms_blob)
    access_token = creds.get("access_token", "")
    ig_account_id = (integ.config or {}).get("instagram_business_account_id", "")
    if not access_token or not ig_account_id:
        return

    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    adapter = InstagramGraphAdapter(access_token=access_token, ig_account_id=ig_account_id)

    try:
        daily_results = adapter.get_account_insights(_DAILY_METRICS, period="day")
    except httpx.HTTPStatusError as exc:
        log.warning(
            "instagram_insights_api_error", tenant_id=integ.tenant_id, call="daily",
            status=exc.response.status_code, body=exc.response.text[:300],
        )
        return  # account-level token/permission problem -- nothing else here will work either

    daily_values = {}
    for metric in daily_results:
        vals = metric.get("values", [])
        if vals:
            daily_values[metric["name"]] = vals[-1].get("value")

    try:
        account_fields = adapter.get_account_fields()
    except httpx.HTTPStatusError as exc:
        log.warning("instagram_insights_api_error", tenant_id=integ.tenant_id, call="account_fields",
                    status=exc.response.status_code, body=exc.response.text[:300])
        account_fields = {}

    try:
        engagement = adapter.get_account_engagement_totals(_ENGAGEMENT_METRICS)
    except httpx.HTTPStatusError as exc:
        log.warning("instagram_insights_api_error", tenant_id=integ.tenant_id, call="engagement",
                    status=exc.response.status_code, body=exc.response.text[:300])
        engagement = {}

    demographics = {}
    for breakdown in _DEMOGRAPHIC_BREAKDOWNS:
        try:
            demographics[breakdown] = adapter.get_follower_demographics(breakdown)
        except httpx.HTTPStatusError as exc:
            # Confirmed live for city/country/age/gender on a 5000+ follower
            # account; a smaller/newer account may not clear whatever
            # minimum-audience threshold Meta enforces -- that's a real
            # "not enough data yet" case, not a bug, so this metric is just
            # left out rather than failing the whole snapshot.
            log.info("instagram_demographics_unavailable", tenant_id=integ.tenant_id, breakdown=breakdown,
                     status=exc.response.status_code)

    db.add(InstagramInsightsSnapshot(
        id=str(uuid.uuid4()),
        tenant_id=integ.tenant_id,
        ig_account_id=ig_account_id,
        reach=daily_values.get("reach"),
        profile_views=daily_values.get("profile_views"),
        follower_count=daily_values.get("follower_count"),
        followers_count=account_fields.get("followers_count"),
        following_count=account_fields.get("follows_count"),
        media_count=account_fields.get("media_count"),
        accounts_engaged=engagement.get("accounts_engaged"),
        total_interactions=engagement.get("total_interactions"),
        likes=engagement.get("likes"),
        comments=engagement.get("comments"),
        shares=engagement.get("shares"),
        saves=engagement.get("saves"),
        replies=engagement.get("replies"),
        profile_links_taps=engagement.get("profile_links_taps"),
        demographics=demographics,
        raw={"daily": daily_results, "account_fields": account_fields, "engagement": engagement},
    ))

    _poll_recent_posts(db, integ.tenant_id, adapter)


def _poll_recent_posts(db, tenant_id: str, adapter) -> None:
    try:
        media_items = adapter.get_recent_media(limit=_RECENT_MEDIA_LIMIT)
    except httpx.HTTPStatusError as exc:
        log.warning("instagram_insights_api_error", tenant_id=tenant_id, call="recent_media",
                    status=exc.response.status_code, body=exc.response.text[:300])
        return

    for item in media_items:
        media_id = item.get("id")
        if not media_id:
            continue

        # Per meta_graph.py's get_media_insights docstring: not confirmed
        # whether an unsupported metric/media_type combination is silently
        # omitted or raises for the whole call -- either way, one bad post
        # must not stop the rest of the batch from being saved.
        try:
            media_insights = adapter.get_media_insights(media_id, _MEDIA_INSIGHT_METRICS)
        except httpx.HTTPStatusError as exc:
            log.info("instagram_media_insights_unavailable", tenant_id=tenant_id, media_id=media_id,
                     status=exc.response.status_code)
            media_insights = {}

        existing = (
            db.query(InstagramPostSnapshot)
            .filter_by(tenant_id=tenant_id, media_id=media_id)
            .first()
        )
        target = existing or InstagramPostSnapshot(id=str(uuid.uuid4()), tenant_id=tenant_id, media_id=media_id)
        target.caption = item.get("caption")
        target.media_type = item.get("media_type")
        target.permalink = item.get("permalink")
        target.thumbnail_url = item.get("thumbnail_url") or item.get("media_url")
        target.posted_at = item.get("timestamp")
        target.like_count = item.get("like_count")
        target.comments_count = item.get("comments_count")
        target.reach = media_insights.get("reach")
        target.saved = media_insights.get("saved")
        target.shares = media_insights.get("shares")
        target.total_interactions = media_insights.get("total_interactions")
        if not existing:
            db.add(target)
