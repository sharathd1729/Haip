"""
Goals API — CRUD for metric targets. Goal evaluator worker reads these nightly.
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, get_workspace_context, require_module
from app.models.user import User
from app.models.dashboard_v2 import Goal
from app.models.base import gen_uuid

router = APIRouter(prefix="/goals", tags=["goals"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class GoalCreate(BaseModel):
    metric_key: str
    name: str
    target_value: str          # numeric as string (e.g. "500000" for ₹5L)
    period_type: str           # monthly|quarterly|annual
    period_start: datetime
    period_end: datetime
    property_ids: Optional[list[str]] = None   # null = all properties
    alert_at_pct: int = 80


class GoalUpdate(BaseModel):
    name: Optional[str] = None
    target_value: Optional[str] = None
    alert_at_pct: Optional[int] = None
    property_ids: Optional[list[str]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_goals(
    metric_key: Optional[str] = Query(default=None),
    period_type: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    """List all goals for this workspace."""
    q = db.query(Goal).filter(Goal.workspace_id == current_user.tenant_id)
    if metric_key:
        q = q.filter(Goal.metric_key == metric_key)
    if period_type:
        q = q.filter(Goal.period_type == period_type)
    goals = q.order_by(Goal.period_start.desc()).all()
    return {"goals": [_goal_row(g) for g in goals], "total": len(goals)}


@router.post("", status_code=201)
def create_goal(
    body: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    goal = Goal(
        id=gen_uuid(),
        workspace_id=current_user.tenant_id,
        metric_key=body.metric_key,
        name=body.name,
        target_value=body.target_value,
        period_type=body.period_type,
        period_start=body.period_start,
        period_end=body.period_end,
        property_ids=body.property_ids,
        alert_at_pct=body.alert_at_pct,
        owner_id=current_user.id,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _goal_row(goal)


@router.get("/progress")
def goals_progress(
    period_type: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    """
    Return each active goal with current-value progress from metric_snapshots.
    Uses latest snapshot for the goal's metric_key.
    """
    from app.models.dashboard_v2 import MetricSnapshot
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    tid = current_user.tenant_id

    q = db.query(Goal).filter(
        Goal.workspace_id == tid,
        Goal.period_end >= now,
    )
    if period_type:
        q = q.filter(Goal.period_type == period_type)
    goals = q.all()

    # Batch-fetch latest snapshot for each metric key
    metric_keys = list({g.metric_key for g in goals})
    subq = (
        db.query(
            MetricSnapshot.metric_key,
            func.max(MetricSnapshot.period_date).label("max_date"),
        )
        .filter(
            MetricSnapshot.workspace_id == tid,
            MetricSnapshot.metric_key.in_(metric_keys),
        )
        .group_by(MetricSnapshot.metric_key)
        .subquery()
    )
    latest = db.query(MetricSnapshot).join(
        subq,
        (MetricSnapshot.metric_key == subq.c.metric_key) &
        (MetricSnapshot.period_date == subq.c.max_date),
    ).filter(MetricSnapshot.workspace_id == tid).all()
    latest_map = {r.metric_key: float(r.value) for r in latest}

    result = []
    for g in goals:
        target = float(g.target_value)
        current = latest_map.get(g.metric_key, 0.0)
        pct = round((current / target * 100) if target > 0 else 0.0, 1)
        result.append({
            **_goal_row(g),
            "current_value": current,
            "progress_pct": pct,
            "on_track": pct >= g.alert_at_pct,
        })
    return {"goals": result}


@router.get("/{goal_id}/status")
def get_goal_status(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    """Return goal with current progress and on-track status."""
    from app.models.dashboard_v2 import MetricSnapshot
    from sqlalchemy import func

    goal = _get_goal_or_404(db, goal_id, current_user.tenant_id)
    tid = current_user.tenant_id

    latest = (
        db.query(MetricSnapshot)
        .filter(
            MetricSnapshot.workspace_id == tid,
            MetricSnapshot.metric_key == goal.metric_key,
            MetricSnapshot.granularity == "day",
        )
        .order_by(MetricSnapshot.period_date.desc())
        .first()
    )
    current_val = float(latest.value) if latest else 0.0
    target_val = float(goal.target_value)
    pct = round((current_val / target_val * 100) if target_val > 0 else 0.0, 1)
    return {
        **_goal_row(goal),
        "current_value": current_val,
        "progress_pct": pct,
        "on_track": pct >= goal.alert_at_pct,
        "last_updated": latest.period_date.isoformat() if latest else None,
    }


@router.get("/{goal_id}")
def get_goal(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    return _goal_row(_get_goal_or_404(db, goal_id, current_user.tenant_id))


@router.patch("/{goal_id}")
def update_goal(
    goal_id: str,
    body: GoalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    goal = _get_goal_or_404(db, goal_id, current_user.tenant_id)
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(goal, field, val)
    db.commit()
    db.refresh(goal)
    return _goal_row(goal)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _ctx=Depends(require_module("analytics")),
):
    goal = _get_goal_or_404(db, goal_id, current_user.tenant_id)
    db.delete(goal)
    db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_goal_or_404(db: Session, goal_id: str, workspace_id: str) -> Goal:
    g = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.workspace_id == workspace_id,
    ).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    return g


def _goal_row(g: Goal) -> dict:
    return {
        "id": g.id,
        "metric_key": g.metric_key,
        "name": g.name,
        "target_value": g.target_value,
        "period_type": g.period_type,
        "period_start": g.period_start.isoformat() if g.period_start else None,
        "period_end": g.period_end.isoformat() if g.period_end else None,
        "property_ids": g.property_ids,
        "alert_at_pct": g.alert_at_pct,
        "owner_id": g.owner_id,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }
