"""
Organic Instagram insights -- read endpoint for the owner-facing
dashboard. Snapshots are written daily by instagram_insights_poll.py;
this endpoint only reads what's already stored, never calls Meta inline.

Deliberately NOT gated behind require_module("analytics") -- that module
was deactivated tenant-wide 2026-08-08 during an in-progress rebuild (see
frontend/src/app/dashboard/analytics/page.tsx's own comment: it 403s
every /analytics/* endpoint and no nav link points there anymore). Gating
a brand-new feature behind an intentionally-disabled module would make it
invisible to every tenant.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.workers.tasks.instagram_insights_poll import InstagramInsightsSnapshot, InstagramPostSnapshot

router = APIRouter(prefix="/instagram-insights", tags=["instagram-insights"])


class InstagramInsightPoint(BaseModel):
    date: str
    reach: int | None = None
    profile_views: int | None = None
    follower_count: int | None = None


class DemographicResult(BaseModel):
    label: str
    value: int


class InstagramPost(BaseModel):
    media_id: str
    caption: str | None = None
    media_type: str | None = None
    permalink: str | None = None
    thumbnail_url: str | None = None
    posted_at: str | None = None
    like_count: int | None = None
    comments_count: int | None = None
    reach: int | None = None
    saved: int | None = None
    shares: int | None = None
    total_interactions: int | None = None


class InstagramOverview(BaseModel):
    followers_count: int | None = None
    following_count: int | None = None
    media_count: int | None = None
    accounts_engaged: int | None = None
    total_interactions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    replies: int | None = None
    profile_links_taps: int | None = None


class InstagramInsightsResponse(BaseModel):
    connected: bool
    overview: InstagramOverview | None = None
    trend: list[InstagramInsightPoint]
    demographics: dict[str, list[DemographicResult]]
    posts: list[InstagramPost]


def _demographic_results(raw: list[dict] | None) -> list[DemographicResult]:
    if not raw:
        return []
    out = []
    for row in raw:
        dims = row.get("dimension_values") or []
        out.append(DemographicResult(label=", ".join(str(d) for d in dims) or "Unknown", value=row.get("value") or 0))
    out.sort(key=lambda r: r.value, reverse=True)
    return out[:10]


@router.get("", response_model=InstagramInsightsResponse)
def get_instagram_insights(
    range_days: int = Query(default=30, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InstagramInsightsResponse:
    since = datetime.now(timezone.utc) - timedelta(days=range_days)
    rows = (
        db.query(InstagramInsightsSnapshot)
        .filter(
            InstagramInsightsSnapshot.tenant_id == current_user.tenant_id,
            InstagramInsightsSnapshot.created_at >= since,
        )
        .order_by(InstagramInsightsSnapshot.created_at.asc())
        .all()
    )

    if not rows:
        return InstagramInsightsResponse(connected=False, trend=[], demographics={}, posts=[])

    latest = rows[-1]
    demographics_raw = latest.demographics or {}

    posts = (
        db.query(InstagramPostSnapshot)
        .filter_by(tenant_id=current_user.tenant_id)
        .order_by(InstagramPostSnapshot.posted_at.desc())
        .limit(12)
        .all()
    )

    return InstagramInsightsResponse(
        connected=True,
        overview=InstagramOverview(
            followers_count=latest.followers_count, following_count=latest.following_count,
            media_count=latest.media_count, accounts_engaged=latest.accounts_engaged,
            total_interactions=latest.total_interactions, likes=latest.likes,
            comments=latest.comments, shares=latest.shares, saves=latest.saves,
            replies=latest.replies, profile_links_taps=latest.profile_links_taps,
        ),
        trend=[
            InstagramInsightPoint(
                date=r.created_at.date().isoformat(),
                reach=r.reach, profile_views=r.profile_views, follower_count=r.follower_count,
            )
            for r in rows
        ],
        demographics={
            breakdown: _demographic_results(demographics_raw.get(breakdown))
            for breakdown in ("city", "country", "age", "gender")
        },
        posts=[
            InstagramPost(
                media_id=p.media_id, caption=p.caption, media_type=p.media_type,
                permalink=p.permalink, thumbnail_url=p.thumbnail_url, posted_at=p.posted_at,
                like_count=p.like_count, comments_count=p.comments_count,
                reach=p.reach, saved=p.saved, shares=p.shares, total_interactions=p.total_interactions,
            )
            for p in posts
        ],
    )
