"""Dashboard summary endpoint — real numbers per tenant."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from pydantic import BaseModel

import redis

from app.core.database import get_db
from app.core.config import settings
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.call import Call, CallDisposition
from app.models.guest import Guest
from app.models.score import CallScore
from app.models.inquiry import Inquiry, InquiryStage
from app.models.conversation import Conversation
from app.models.tenant import Tenant
from app.models.dashboard_widget import DashboardWidget
from app.services.widget_service import (
    WIDGET_REGISTRY, detect_modules, get_default_widgets, upsert_widget,
)
from app.workers.tasks.generate_widgets import generate_widgets

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_redis = redis.from_url(settings.REDIS_URL, decode_responses=True)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class WidgetSnapshot(BaseModel):
    key: str
    title: str
    state: str   # unavailable | early_signal | full_insight
    summary: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    generated_at: Optional[datetime] = None
    next_refresh_at: Optional[datetime] = None


class DashboardConfigIn(BaseModel):
    selected_widgets: list[str]


@router.get("")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = current_user.tenant_id
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # ── Counts ────────────────────────────────────────────────────────────────
    total_calls = db.query(func.count(Call.id)).filter_by(tenant_id=tid).scalar() or 0
    calls_this_week = (
        db.query(func.count(Call.id))
        .filter(Call.tenant_id == tid, Call.created_at >= week_ago)
        .scalar() or 0
    )
    total_guests = db.query(func.count(Guest.id)).filter_by(tenant_id=tid).scalar() or 0

    # ── QA avg ────────────────────────────────────────────────────────────────
    scored_calls = (
        db.query(func.count(Call.id))
        .filter(Call.tenant_id == tid, Call.ai_score_status == "done", Call.ai_score.isnot(None))
        .scalar() or 0
    )
    avg_qa_row = (
        db.query(func.avg(Call.ai_score))
        .filter(Call.tenant_id == tid, Call.ai_score.isnot(None))
        .scalar()
    )
    avg_qa_score = float(avg_qa_row) if avg_qa_row else None

    # ── Recent calls (last 20) ────────────────────────────────────────────────
    recent_raw = (
        db.query(Call)
        .filter_by(tenant_id=tid)
        .order_by(Call.created_at.desc())
        .limit(20)
        .all()
    )

    # Guest name lookup (batch)
    guest_ids = [c.guest_id for c in recent_raw if c.guest_id]
    guests = {g.id: g for g in db.query(Guest).filter(Guest.id.in_(guest_ids)).all()}

    recent_calls = []
    for c in recent_raw:
        g = guests.get(c.guest_id)
        disp = c.human_disposition or c.ai_disposition
        recent_calls.append({
            "id": c.id,
            "guest_phone": c.from_number,
            "guest_name": g.name if g else None,
            "qa_score": float(c.ai_score) if c.ai_score else None,
            "disposition": disp.value if hasattr(disp, "value") else (disp or "pending"),
            "started_at": c.started_at,
            "duration_seconds": c.duration_seconds or 0,
        })

    # ── Active inquiries (non-terminal stages) ───────────────────────────────
    _terminal_stages = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
    active_inquiries = (
        db.query(func.count(Inquiry.id))
        .filter(Inquiry.tenant_id == tid, Inquiry.stage.not_in(_terminal_stages))
        .scalar() or 0
    )

    # ── Open conversations ────────────────────────────────────────────────────
    open_conversations = (
        db.query(func.count(Conversation.id))
        .filter(Conversation.tenant_id == tid, Conversation.is_open == True)  # noqa: E712
        .scalar() or 0
    )

    return {
        "total_calls": total_calls,
        "calls_this_week": calls_this_week,
        "total_guests": total_guests,
        "active_inquiries": active_inquiries,
        "open_conversations": open_conversations,
        "scored_calls": scored_calls,
        "avg_qa_score": avg_qa_score,
        "recent_calls": recent_calls,
    }


# ─── Widget endpoints ─────────────────────────────────────────────────────────

@router.get("/widgets")
def get_widgets(
    range_days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return widget snapshots for the tenant's selected (or default) widget set."""
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    modules = detect_modules(db, tenant)
    config = tenant.dashboard_config or {}
    selected = config.get("selected_widgets") or get_default_widgets(modules)

    rows = {
        r.widget_key: r
        for r in db.query(DashboardWidget).filter(
            DashboardWidget.tenant_id == tenant.id,
            DashboardWidget.widget_key.in_(selected),
        ).all()
    }

    snapshots = []
    for key in selected:
        defn = WIDGET_REGISTRY.get(key)
        if not defn:
            continue
        row = rows.get(key)
        if row:
            snapshots.append(WidgetSnapshot(
                key=key,
                title=defn.title,
                state=row.state,
                summary=row.summary,
                data=row.data,
                generated_at=row.generated_at,
                next_refresh_at=row.next_refresh_at,
            ))
        else:
            # No cached snapshot yet — compute inline (first-time visit)
            row = upsert_widget(db, tenant, key, modules, range_days)
            db.commit()
            snapshots.append(WidgetSnapshot(
                key=key,
                title=defn.title,
                state=row.state,
                summary=row.summary,
                data=row.data,
                generated_at=row.generated_at,
                next_refresh_at=row.next_refresh_at,
            ))

    return {"widgets": [s.model_dump() for s in snapshots], "available_modules": sorted(modules)}


@router.get("/widget-library")
def get_widget_library(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full 18-widget catalogue with per-tenant state."""
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    modules = detect_modules(db, tenant)
    rows = {
        r.widget_key: r.state
        for r in db.query(DashboardWidget).filter(
            DashboardWidget.tenant_id == tenant.id,
        ).all()
    }

    library = []
    for key, defn in WIDGET_REGISTRY.items():
        missing = [m for m in defn.required_modules if m not in modules]
        state = rows.get(key, "unavailable" if missing else "early_signal")
        library.append({
            "key": key,
            "title": defn.title,
            "description": defn.description,
            "category": defn.category,
            "state": state,
            "required_modules": defn.required_modules,
            "missing_modules": missing,
        })

    return {"library": library}


@router.put("/config")
def update_dashboard_config(
    body: DashboardConfigIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
):
    """Save selected widget keys (max 8). Triggers background generation for new keys."""
    if len(body.selected_widgets) > 8:
        raise HTTPException(status_code=422, detail="Maximum 8 widgets allowed")
    unknown = [k for k in body.selected_widgets if k not in WIDGET_REGISTRY]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown widget keys: {unknown}")

    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    old_config = tenant.dashboard_config or {}
    old_keys = set(old_config.get("selected_widgets") or [])
    new_keys = set(body.selected_widgets)
    added = list(new_keys - old_keys)

    tenant.dashboard_config = {
        "selected_widgets": body.selected_widgets,
        "customized_at": datetime.now(timezone.utc).isoformat(),
    }
    db.commit()

    if added:
        generate_widgets.delay(tenant_id=tenant.id, widget_keys=added)

    return {"ok": True, "selected_widgets": body.selected_widgets}


@router.post("/widgets/refresh")
def refresh_widget(
    widget_key: str = Query(...),
    range_days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually refresh a single widget (rate-limited: once per 5 min per widget)."""
    if widget_key not in WIDGET_REGISTRY:
        raise HTTPException(status_code=422, detail="Unknown widget key")

    tid = current_user.tenant_id
    rate_key = f"widget_refresh:{tid}:{widget_key}"
    if _redis.get(rate_key):
        raise HTTPException(status_code=429, detail="Refresh allowed once per 5 minutes per widget")
    _redis.setex(rate_key, 300, "1")

    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    modules = detect_modules(db, tenant)
    row = upsert_widget(db, tenant, widget_key, modules, range_days)
    db.commit()
    defn = WIDGET_REGISTRY[widget_key]
    return WidgetSnapshot(
        key=widget_key,
        title=defn.title,
        state=row.state,
        summary=row.summary,
        data=row.data,
        generated_at=row.generated_at,
        next_refresh_at=row.next_refresh_at,
    ).model_dump()
