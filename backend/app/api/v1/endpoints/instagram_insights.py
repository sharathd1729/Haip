"""
Organic Instagram account insights -- read endpoint for the owner-facing
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
from app.workers.tasks.instagram_insights_poll import InstagramInsightsSnapshot

router = APIRouter(prefix="/instagram-insights", tags=["instagram-insights"])


class InstagramInsightPoint(BaseModel):
    date: str
    reach: int | None = None
    profile_views: int | None = None
    follower_count: int | None = None


class InstagramInsightsResponse(BaseModel):
    connected: bool
    points: list[InstagramInsightPoint]


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
    return InstagramInsightsResponse(
        connected=len(rows) > 0,
        points=[
            InstagramInsightPoint(
                date=r.created_at.date().isoformat(),
                reach=r.reach, profile_views=r.profile_views, follower_count=r.follower_count,
            )
            for r in rows
        ],
    )
