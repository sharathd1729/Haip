"""
Widgets API — registry browsing and per-workspace widget catalogue.
Module-filtered: only widgets whose required_modules are all active are available.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, get_workspace_context
from app.models.user import User
from app.models.widget_registry import WidgetRegistryEntry
from app.services.workspace_context import available_widgets_for_context

router = APIRouter(prefix="/widgets", tags=["widgets"])


@router.get("/registry")
def list_widget_registry(
    category: Optional[str] = Query(default=None),
    available_only: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """
    Return all widgets, annotated with availability for this workspace.
    Pass available_only=true to show only unlocked widgets.
    """
    widgets = available_widgets_for_context(db, ctx)
    if category:
        widgets = [w for w in widgets if w.get("category") == category]
    if available_only:
        widgets = [w for w in widgets if w["available"]]
    return {"widgets": widgets, "total": len(widgets)}


@router.get("/registry/{widget_key}")
def get_widget_definition(
    widget_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Return full definition + availability for one widget type."""
    row = db.query(WidgetRegistryEntry).filter(
        WidgetRegistryEntry.widget_key == widget_key
    ).first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Widget not found")

    req_modules: list[str] = row.required_modules or []
    req_flags: list[str] = row.required_feature_flags or []
    available = (
        all(m in ctx.active_modules for m in req_modules) and
        all(ctx.flag(f) for f in req_flags)
    )

    return {
        "key": row.widget_key,
        "name": row.widget_name,
        "description": row.description,
        "category": row.category,
        "widget_type": row.widget_type,
        "required_modules": req_modules,
        "required_metrics": row.required_metrics,
        "default_metric_bindings": row.default_metric_bindings,
        "min_data_rows": row.min_data_rows,
        "refresh_hours": row.refresh_hours,
        "available": available,
        "missing_modules": [m for m in req_modules if m not in ctx.active_modules],
        "missing_flags": [f for f in req_flags if not ctx.flag(f)],
    }


@router.post("/{widget_instance_id}/refresh", status_code=202)
def refresh_widget(
    widget_instance_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """
    Bust cached_data on a widget instance and trigger recompute.
    Returns 202 — client should re-fetch snapshot after a short delay.
    """
    from app.models.dashboard_v2 import DashboardWidgetInstance
    wi = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.id == widget_instance_id,
        DashboardWidgetInstance.workspace_id == current_user.tenant_id,
    ).first()
    if not wi:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Widget instance not found")
    wi.cached_data = None
    wi.cached_at = None
    db.commit()
    return {"widget_instance_id": widget_instance_id, "status": "refresh_queued"}


@router.get("/{widget_instance_id}/data")
def get_widget_data(
    widget_instance_id: str,
    range_days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """
    Return pre-computed cached_data for a widget instance.
    Falls back to latest metric snapshots if no cache.
    """
    from fastapi import HTTPException
    from app.models.dashboard_v2 import DashboardWidgetInstance, MetricSnapshot
    from app.models.metric_registry import MetricRegistry
    from datetime import datetime, timezone, timedelta

    wi = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.id == widget_instance_id,
        DashboardWidgetInstance.workspace_id == current_user.tenant_id,
    ).first()
    if not wi:
        raise HTTPException(status_code=404, detail="Widget instance not found")

    if wi.cached_data:
        return {"widget_instance_id": widget_instance_id, "data": wi.cached_data, "cached_at": wi.cached_at.isoformat() if wi.cached_at else None}

    # No cache — serve latest snapshots for bound metrics
    bound_metrics: list[str] = list(wi.metric_bindings.values()) if wi.metric_bindings else []
    if not bound_metrics:
        reg = db.query(WidgetRegistryEntry).filter(WidgetRegistryEntry.widget_key == wi.widget_key).first()
        bound_metrics = reg.required_metrics or [] if reg else []

    start = datetime.now(timezone.utc) - timedelta(days=range_days)
    snaps = db.query(MetricSnapshot).filter(
        MetricSnapshot.workspace_id == current_user.tenant_id,
        MetricSnapshot.metric_key.in_(bound_metrics),
        MetricSnapshot.granularity == "day",
        MetricSnapshot.period_date >= start,
    ).order_by(MetricSnapshot.period_date.asc()).all()

    data = {}
    for s in snaps:
        data.setdefault(s.metric_key, []).append({"date": s.period_date.isoformat(), "value": s.value})

    return {"widget_instance_id": widget_instance_id, "data": data, "cached_at": None}


@router.get("/categories")
def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Return distinct categories with counts and availability status."""
    all_widgets = available_widgets_for_context(db, ctx)
    cats: dict[str, dict] = {}
    for w in all_widgets:
        cat = w.get("category") or "other"
        if cat not in cats:
            cats[cat] = {"category": cat, "total": 0, "available": 0}
        cats[cat]["total"] += 1
        if w["available"]:
            cats[cat]["available"] += 1
    return {"categories": list(cats.values())}
