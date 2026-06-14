"""
Metrics API — list registry, fetch snapshots, query live metric values.
Module-filtered: only metrics whose module_code is in active_modules are returned.
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, get_workspace_context
from app.models.user import User
from app.models.metric_registry import MetricRegistry
from app.models.dashboard_v2 import MetricSnapshot
from app.services.workspace_context import available_metrics_for_context

router = APIRouter(prefix="/metrics", tags=["metrics"])


# ── Registry ──────────────────────────────────────────────────────────────────

@router.get("/registry")
def list_metric_registry(
    module: Optional[str] = Query(default=None, description="Filter by module code"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """
    Return all metrics available to this workspace (filtered by active modules).
    Optionally filter further by module code.
    """
    metrics = available_metrics_for_context(db, ctx)
    if module:
        metrics = [m for m in metrics if m["module"] == module]
    return {"metrics": metrics, "total": len(metrics)}


@router.get("/registry/{metric_key}")
def get_metric_definition(
    metric_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Return full definition of a single metric (only if module is active)."""
    row = db.query(MetricRegistry).filter(
        MetricRegistry.metric_key == metric_key
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Metric not found")
    if row.module_code not in ctx.active_modules:
        raise HTTPException(status_code=403, detail=f"Module '{row.module_code}' not active")
    return {
        "key": row.metric_key,
        "name": row.metric_name,
        "description": row.description,
        "module": row.module_code,
        "unit": row.unit,
        "aggregation": row.aggregation_type,
        "compatible_widget_types": row.compatible_widget_types,
        "refresh_frequency": row.refresh_frequency,
        "cache_ttl_seconds": row.cache_ttl_seconds,
    }


# ── Snapshots ─────────────────────────────────────────────────────────────────

@router.get("/snapshots")
def list_snapshots(
    metric_key: Optional[str] = Query(default=None),
    granularity: str = Query(default="day", regex="^(day|week|month)$"),
    range_days: int = Query(default=30, ge=1, le=365),
    property_id: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Return pre-aggregated metric snapshots for the workspace."""
    start = datetime.now(timezone.utc) - timedelta(days=range_days)
    tid = current_user.tenant_id

    q = db.query(MetricSnapshot).filter(
        MetricSnapshot.workspace_id == tid,
        MetricSnapshot.granularity == granularity,
        MetricSnapshot.period_date >= start,
    )
    if metric_key:
        q = q.filter(MetricSnapshot.metric_key == metric_key)
    if property_id:
        q = q.filter(MetricSnapshot.property_id == property_id)

    rows = q.order_by(MetricSnapshot.period_date.asc()).limit(500).all()

    # Filter to active-module metrics only
    active_modules = set(ctx.active_modules)
    metric_modules: dict[str, str] = {}
    for r in db.query(MetricRegistry.metric_key, MetricRegistry.module_code).all():
        metric_modules[r.metric_key] = r.module_code

    return {
        "snapshots": [
            {
                "metric_key": r.metric_key,
                "period_date": r.period_date.isoformat(),
                "granularity": r.granularity,
                "value": r.value,
                "property_id": r.property_id,
                "dimensions": r.dimensions,
                "computed_at": r.computed_at.isoformat() if r.computed_at else None,
            }
            for r in rows
            if metric_modules.get(r.metric_key, "") in active_modules
        ],
        "range_days": range_days,
        "granularity": granularity,
    }


@router.get("/{metric_key}/data")
def get_metric_data(
    metric_key: str,
    range_days: int = Query(default=30, ge=1, le=365),
    granularity: str = Query(default="day", regex="^(day|week|month)$"),
    property_id: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Latest snapshot values for a single metric over a date range."""
    row = db.query(MetricRegistry).filter(MetricRegistry.metric_key == metric_key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Metric not found")
    if row.module_code not in ctx.active_modules:
        raise HTTPException(status_code=403, detail=f"Module '{row.module_code}' not active")

    start = datetime.now(timezone.utc) - timedelta(days=range_days)
    q = db.query(MetricSnapshot).filter(
        MetricSnapshot.workspace_id == current_user.tenant_id,
        MetricSnapshot.metric_key == metric_key,
        MetricSnapshot.granularity == granularity,
        MetricSnapshot.period_date >= start,
    )
    if property_id:
        q = q.filter(MetricSnapshot.property_id == property_id)
    snaps = q.order_by(MetricSnapshot.period_date.asc()).all()
    return {
        "metric_key": metric_key,
        "metric_name": row.metric_name,
        "unit": row.unit,
        "granularity": granularity,
        "range_days": range_days,
        "data": [{"date": s.period_date.isoformat(), "value": s.value, "dimensions": s.dimensions} for s in snaps],
    }


@router.get("/{metric_key}/series")
def get_metric_series(
    metric_key: str,
    compare_days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Current period vs prior period series for sparkline comparison."""
    row = db.query(MetricRegistry).filter(MetricRegistry.metric_key == metric_key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Metric not found")
    if row.module_code not in ctx.active_modules:
        raise HTTPException(status_code=403, detail=f"Module '{row.module_code}' not active")

    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=compare_days)
    prior_start = current_start - timedelta(days=compare_days)

    def _fetch(start, end):
        return db.query(MetricSnapshot).filter(
            MetricSnapshot.workspace_id == current_user.tenant_id,
            MetricSnapshot.metric_key == metric_key,
            MetricSnapshot.granularity == "day",
            MetricSnapshot.period_date >= start,
            MetricSnapshot.period_date < end,
        ).order_by(MetricSnapshot.period_date.asc()).all()

    current = _fetch(current_start, now)
    prior = _fetch(prior_start, current_start)

    return {
        "metric_key": metric_key,
        "compare_days": compare_days,
        "current": [{"date": s.period_date.isoformat(), "value": s.value} for s in current],
        "prior": [{"date": s.period_date.isoformat(), "value": s.value} for s in prior],
    }


@router.get("/{metric_key}/drill")
def drill_metric(
    metric_key: str,
    dimension: str = Query(default="property_id", description="Dimension to group by"),
    range_days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Aggregate a metric broken down by a dimension (e.g. property_id)."""
    from sqlalchemy import func as sqlfunc, cast
    from sqlalchemy import Numeric

    row = db.query(MetricRegistry).filter(MetricRegistry.metric_key == metric_key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Metric not found")
    if row.module_code not in ctx.active_modules:
        raise HTTPException(status_code=403, detail=f"Module '{row.module_code}' not active")

    start = datetime.now(timezone.utc) - timedelta(days=range_days)
    snaps = db.query(MetricSnapshot).filter(
        MetricSnapshot.workspace_id == current_user.tenant_id,
        MetricSnapshot.metric_key == metric_key,
        MetricSnapshot.granularity == "day",
        MetricSnapshot.period_date >= start,
    ).all()

    groups: dict[str, list[float]] = {}
    for s in snaps:
        key = str(s.property_id) if s.property_id else "all"
        groups.setdefault(key, []).append(float(s.value))

    agg_type = row.aggregation_type or "sum"
    result = []
    for dim_val, vals in groups.items():
        if agg_type == "avg":
            agg = sum(vals) / len(vals) if vals else 0
        elif agg_type == "count":
            agg = len(vals)
        else:
            agg = sum(vals)
        result.append({"dimension": dimension, "value": dim_val, "aggregate": round(agg, 4)})

    return {"metric_key": metric_key, "dimension": dimension, "breakdown": result}


@router.get("/{metric_key}/compare")
def compare_metric(
    metric_key: str,
    period_a_days: int = Query(default=30, ge=1, le=365),
    period_b_days: int = Query(default=30, ge=1, le=365),
    offset_b: int = Query(default=30, ge=1, le=365, description="Days ago to start period B"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Compare two arbitrary periods for a metric."""
    row = db.query(MetricRegistry).filter(MetricRegistry.metric_key == metric_key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Metric not found")
    if row.module_code not in ctx.active_modules:
        raise HTTPException(status_code=403, detail=f"Module '{row.module_code}' not active")

    now = datetime.now(timezone.utc)
    a_end = now
    a_start = now - timedelta(days=period_a_days)
    b_end = now - timedelta(days=offset_b)
    b_start = b_end - timedelta(days=period_b_days)

    def _total(start, end):
        rows = db.query(MetricSnapshot).filter(
            MetricSnapshot.workspace_id == current_user.tenant_id,
            MetricSnapshot.metric_key == metric_key,
            MetricSnapshot.granularity == "day",
            MetricSnapshot.period_date >= start,
            MetricSnapshot.period_date < end,
        ).all()
        vals = [float(r.value) for r in rows]
        if not vals:
            return 0.0
        agg = row.aggregation_type or "sum"
        return sum(vals) if agg != "avg" else sum(vals) / len(vals)

    val_a = _total(a_start, a_end)
    val_b = _total(b_start, b_end)
    delta_pct = round(((val_a - val_b) / val_b * 100) if val_b else 0.0, 1)

    return {
        "metric_key": metric_key,
        "period_a": {"start": a_start.date().isoformat(), "end": a_end.date().isoformat(), "value": round(val_a, 4)},
        "period_b": {"start": b_start.date().isoformat(), "end": b_end.date().isoformat(), "value": round(val_b, 4)},
        "delta_pct": delta_pct,
        "direction": "up" if delta_pct > 0 else ("down" if delta_pct < 0 else "flat"),
    }


@router.get("/snapshots/latest")
def latest_snapshot_per_metric(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Return the most recent snapshot value for each available metric."""
    from sqlalchemy import func
    tid = current_user.tenant_id

    subq = (
        db.query(
            MetricSnapshot.metric_key,
            func.max(MetricSnapshot.period_date).label("max_date"),
        )
        .filter(MetricSnapshot.workspace_id == tid)
        .group_by(MetricSnapshot.metric_key)
        .subquery()
    )

    rows = (
        db.query(MetricSnapshot)
        .join(
            subq,
            (MetricSnapshot.metric_key == subq.c.metric_key) &
            (MetricSnapshot.period_date == subq.c.max_date),
        )
        .filter(MetricSnapshot.workspace_id == tid)
        .all()
    )

    active_modules = set(ctx.active_modules)
    metric_modules: dict[str, str] = {
        r.metric_key: r.module_code
        for r in db.query(MetricRegistry.metric_key, MetricRegistry.module_code).all()
    }

    return {
        "latest": {
            r.metric_key: {
                "value": r.value,
                "period_date": r.period_date.isoformat(),
                "granularity": r.granularity,
            }
            for r in rows
            if metric_modules.get(r.metric_key, "") in active_modules
        }
    }
