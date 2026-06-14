"""
Dashboards API — CRUD for user-created dashboards, widget instances,
templates, and dashboard shares.
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, get_workspace_context
from app.models.user import User
from app.models.dashboard_v2 import (
    Dashboard, DashboardWidgetInstance, DashboardShare, DashboardTemplate
)
from app.models.base import gen_uuid
from app.services.workspace_context import (
    available_widgets_for_context, available_templates_for_context
)

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class DashboardCreate(BaseModel):
    name: str
    description: Optional[str] = None
    layout_config: dict = {}
    date_range_default: str = "30d"
    visibility: str = "private"
    from_template_key: Optional[str] = None


class DashboardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    layout_config: Optional[dict] = None
    date_range_default: Optional[str] = None
    visibility: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_default: Optional[bool] = None


class WidgetInstanceCreate(BaseModel):
    widget_key: str
    title: Optional[str] = None
    position: dict = {}
    metric_bindings: dict = {}
    filters: dict = {}
    goal_id: Optional[str] = None
    display_config: dict = {}
    refresh_seconds: int = 300


class WidgetInstanceUpdate(BaseModel):
    title: Optional[str] = None
    position: Optional[dict] = None
    metric_bindings: Optional[dict] = None
    filters: Optional[dict] = None
    goal_id: Optional[str] = None
    display_config: Optional[dict] = None
    refresh_seconds: Optional[int] = None


class ShareCreate(BaseModel):
    principal_type: str   # user|role|team
    principal_id: str
    permission: str = "view"    # view|edit|manage
    expires_at: Optional[datetime] = None


# ── Dashboards CRUD ───────────────────────────────────────────────────────────

@router.get("")
def list_dashboards(
    visibility: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all dashboards accessible to the current user in this workspace."""
    q = db.query(Dashboard).filter(Dashboard.workspace_id == current_user.tenant_id)
    if visibility:
        q = q.filter(Dashboard.visibility == visibility)
    dashboards = q.order_by(Dashboard.is_pinned.desc(), Dashboard.created_at.desc()).all()
    return {
        "dashboards": [_dashboard_row(d) for d in dashboards],
        "total": len(dashboards),
    }


@router.post("", status_code=201)
def create_dashboard(
    body: DashboardCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Create a new dashboard, optionally from a template."""
    layout = body.layout_config

    if body.from_template_key:
        tpl = db.query(DashboardTemplate).filter(
            DashboardTemplate.template_key == body.from_template_key
        ).first()
        if tpl:
            layout = tpl.layout_json or layout

    dash = Dashboard(
        id=gen_uuid(),
        workspace_id=current_user.tenant_id,
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        layout_config=layout,
        date_range_default=body.date_range_default,
        visibility=body.visibility,
        from_template_key=body.from_template_key,
    )
    db.add(dash)
    db.commit()
    db.refresh(dash)
    return _dashboard_row(dash)


@router.get("/{dashboard_id}")
def get_dashboard(
    dashboard_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dash = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    widgets = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.dashboard_id == dashboard_id
    ).all()
    shares = db.query(DashboardShare).filter(
        DashboardShare.dashboard_id == dashboard_id
    ).all()
    return {
        **_dashboard_row(dash),
        "widgets": [_widget_row(w) for w in widgets],
        "shares": [_share_row(s) for s in shares],
    }


@router.patch("/{dashboard_id}")
def update_dashboard(
    dashboard_id: str,
    body: DashboardUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dash = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    _assert_owner_or_manage(dash, current_user, db)
    from app.core.cache import snap_bust
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(dash, field, val)
    db.commit()
    db.refresh(dash)
    snap_bust(dashboard_id)
    return _dashboard_row(dash)


@router.delete("/{dashboard_id}", status_code=204)
def delete_dashboard(
    dashboard_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.core.cache import snap_bust
    dash = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    _assert_owner_or_manage(dash, current_user, db)
    db.delete(dash)
    db.commit()
    snap_bust(dashboard_id)


# ── Widget instances ──────────────────────────────────────────────────────────

@router.get("/{dashboard_id}/widgets")
def list_widgets(
    dashboard_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    widgets = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.dashboard_id == dashboard_id
    ).all()
    return {"widgets": [_widget_row(w) for w in widgets]}


@router.post("/{dashboard_id}/widgets", status_code=201)
def add_widget(
    dashboard_id: str,
    body: WidgetInstanceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dash = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    _assert_owner_or_manage(dash, current_user, db)
    wi = DashboardWidgetInstance(
        id=gen_uuid(),
        dashboard_id=dashboard_id,
        workspace_id=current_user.tenant_id,
        widget_key=body.widget_key,
        title=body.title,
        position=body.position,
        metric_bindings=body.metric_bindings,
        filters=body.filters,
        goal_id=body.goal_id,
        display_config=body.display_config,
        refresh_seconds=body.refresh_seconds,
    )
    db.add(wi)
    db.commit()
    db.refresh(wi)
    return _widget_row(wi)


@router.patch("/{dashboard_id}/widgets/{widget_id}")
def update_widget(
    dashboard_id: str,
    widget_id: str,
    body: WidgetInstanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wi = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.id == widget_id,
        DashboardWidgetInstance.dashboard_id == dashboard_id,
        DashboardWidgetInstance.workspace_id == current_user.tenant_id,
    ).first()
    if not wi:
        raise HTTPException(status_code=404, detail="Widget not found")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(wi, field, val)
    db.commit()
    db.refresh(wi)
    return _widget_row(wi)


@router.delete("/{dashboard_id}/widgets/{widget_id}", status_code=204)
def remove_widget(
    dashboard_id: str,
    widget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wi = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.id == widget_id,
        DashboardWidgetInstance.dashboard_id == dashboard_id,
        DashboardWidgetInstance.workspace_id == current_user.tenant_id,
    ).first()
    if not wi:
        raise HTTPException(status_code=404, detail="Widget not found")
    db.delete(wi)
    db.commit()


# ── Clone ─────────────────────────────────────────────────────────────────────

@router.post("/{dashboard_id}/clone", status_code=201)
def clone_dashboard(
    dashboard_id: str,
    name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Duplicate a dashboard and all its widget instances."""
    from app.core.cache import snap_bust
    src = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    new_id = gen_uuid()
    clone = Dashboard(
        id=new_id,
        workspace_id=current_user.tenant_id,
        owner_id=current_user.id,
        name=name or f"{src.name} (copy)",
        description=src.description,
        layout_config=src.layout_config,
        date_range_default=src.date_range_default,
        visibility="private",
        from_template_key=src.from_template_key,
    )
    db.add(clone)
    db.flush()

    src_widgets = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.dashboard_id == dashboard_id
    ).all()
    for wi in src_widgets:
        db.add(DashboardWidgetInstance(
            id=gen_uuid(),
            dashboard_id=new_id,
            workspace_id=current_user.tenant_id,
            widget_key=wi.widget_key,
            title=wi.title,
            position=wi.position,
            metric_bindings=wi.metric_bindings,
            filters=wi.filters,
            goal_id=wi.goal_id,
            display_config=wi.display_config,
            refresh_seconds=wi.refresh_seconds,
        ))
    db.commit()
    db.refresh(clone)
    return _dashboard_row(clone)


# ── Shares ────────────────────────────────────────────────────────────────────

@router.post("/{dashboard_id}/shares", status_code=201)
def add_share(
    dashboard_id: str,
    body: ShareCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dash = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    _assert_owner_or_manage(dash, current_user, db)
    share = DashboardShare(
        id=gen_uuid(),
        dashboard_id=dashboard_id,
        workspace_id=current_user.tenant_id,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        permission=body.permission,
        granted_by=current_user.id,
        expires_at=body.expires_at,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return _share_row(share)


@router.delete("/{dashboard_id}/shares/{share_id}", status_code=204)
def remove_share(
    dashboard_id: str,
    share_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    share = db.query(DashboardShare).filter(
        DashboardShare.id == share_id,
        DashboardShare.dashboard_id == dashboard_id,
        DashboardShare.workspace_id == current_user.tenant_id,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    db.delete(share)
    db.commit()


# ── Snapshot (Render Flow Step 2) ─────────────────────────────────────────────

@router.get("/{dashboard_id}/snapshot")
def dashboard_snapshot(
    dashboard_id: str,
    bust: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """
    Returns dashboard + all widget instances with widget registry metadata
    and availability state (module_required | flag_disabled | early_signal | full_insight).
    Frontend uses this as the single load call for rendering a dashboard.
    L4 Redis cache (5 min). Pass ?bust=true to force refresh.
    """
    from app.models.widget_registry import WidgetRegistryEntry
    from app.core.cache import snap_get, snap_set

    if not bust:
        cached = snap_get(dashboard_id)
        if cached:
            return cached

    dash = _get_dashboard_or_404(db, dashboard_id, current_user.tenant_id)
    widget_instances = db.query(DashboardWidgetInstance).filter(
        DashboardWidgetInstance.dashboard_id == dashboard_id
    ).all()

    # Build registry lookup
    keys = [wi.widget_key for wi in widget_instances]
    reg_rows = db.query(WidgetRegistryEntry).filter(
        WidgetRegistryEntry.widget_key.in_(keys)
    ).all()
    reg_map = {r.widget_key: r for r in reg_rows}

    def _widget_state(wi: DashboardWidgetInstance) -> str:
        reg = reg_map.get(wi.widget_key)
        if not reg:
            return "module_required"
        req_modules: list = reg.required_modules or []
        req_flags: list = reg.required_feature_flags or []
        if not all(m in ctx.active_modules for m in req_modules):
            return "module_required"
        if not all(ctx.flag(f) for f in req_flags):
            return "flag_disabled"
        return "full_insight"

    enriched_widgets = []
    for wi in widget_instances:
        reg = reg_map.get(wi.widget_key)
        enriched_widgets.append({
            **_widget_row(wi),
            "widget_name": reg.widget_name if reg else wi.widget_key,
            "widget_type": reg.widget_type if reg else "kpi",
            "category": reg.category if reg else None,
            "required_modules": reg.required_modules if reg else [],
            "state": _widget_state(wi),
        })

    result = {
        **_dashboard_row(dash),
        "widgets": enriched_widgets,
        "active_modules": ctx.active_modules,
    }
    snap_set(dashboard_id, result)
    return result


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates/list")
def list_templates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """Return all templates with availability based on active modules."""
    return {"templates": available_templates_for_context(db, ctx)}


@router.post("/templates/{template_key}/instantiate", status_code=201)
def instantiate_template(
    template_key: str,
    name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx=Depends(get_workspace_context),
):
    """
    Create a new dashboard from a system template.
    Widgets from layout_json are added as DashboardWidgetInstance rows.
    Locked widgets (missing modules) are added with state noted in title.
    """
    tpl = db.query(DashboardTemplate).filter(
        DashboardTemplate.template_key == template_key
    ).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    dash = Dashboard(
        id=gen_uuid(),
        workspace_id=current_user.tenant_id,
        owner_id=current_user.id,
        name=name or tpl.name,
        description=tpl.description,
        layout_config=tpl.layout_json,
        date_range_default=tpl.default_date_range,
        visibility="private",
        from_template_key=template_key,
    )
    db.add(dash)
    db.flush()

    # Add widget instances from template layout
    widgets_layout = tpl.layout_json.get("widgets", [])
    for w in widgets_layout:
        db.add(DashboardWidgetInstance(
            id=gen_uuid(),
            dashboard_id=dash.id,
            workspace_id=current_user.tenant_id,
            widget_key=w["widget_key"],
            position=w.get("position", {}),
            metric_bindings={},
            filters={},
            display_config={},
            refresh_seconds=300,
        ))

    db.commit()
    db.refresh(dash)
    return {"id": dash.id, "name": dash.name, "template_key": template_key}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_dashboard_or_404(db: Session, dashboard_id: str, workspace_id: str) -> Dashboard:
    dash = db.query(Dashboard).filter(
        Dashboard.id == dashboard_id,
        Dashboard.workspace_id == workspace_id,
    ).first()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return dash


def _assert_owner_or_manage(dash: Dashboard, user: User, db: Session):
    if dash.owner_id == user.id:
        return
    share = db.query(DashboardShare).filter(
        DashboardShare.dashboard_id == dash.id,
        DashboardShare.principal_type == "user",
        DashboardShare.principal_id == user.id,
        DashboardShare.permission.in_(["edit", "manage"]),
    ).first()
    if not share:
        raise HTTPException(status_code=403, detail="Not authorised to modify this dashboard")


def _dashboard_row(d: Dashboard) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "layout_config": d.layout_config,
        "date_range_default": d.date_range_default,
        "visibility": d.visibility,
        "is_pinned": d.is_pinned,
        "is_default": d.is_default,
        "owner_id": d.owner_id,
        "from_template_key": d.from_template_key,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _widget_row(w: DashboardWidgetInstance) -> dict:
    return {
        "id": w.id,
        "dashboard_id": w.dashboard_id,
        "widget_key": w.widget_key,
        "title": w.title,
        "position": w.position,
        "metric_bindings": w.metric_bindings,
        "filters": w.filters,
        "goal_id": w.goal_id,
        "display_config": w.display_config,
        "refresh_seconds": w.refresh_seconds,
        "cached_data": w.cached_data,
        "cached_at": w.cached_at.isoformat() if w.cached_at else None,
    }


def _share_row(s: DashboardShare) -> dict:
    return {
        "id": s.id,
        "principal_type": s.principal_type,
        "principal_id": s.principal_id,
        "permission": s.permission,
        "granted_by": s.granted_by,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
    }
