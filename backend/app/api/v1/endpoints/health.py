"""
X8 — Dashboard health endpoint.

Returns per-integration health for the status bar.
Health computed as:
  green  — last_sync < 5 min ago (or never-configured / not applicable)
  yellow — last_sync 5-15 min ago, OR integration connected but queue backing up
  red    — last_sync > 15 min ago, OR integration in error state
  unknown — integration not configured / no data yet
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/health", tags=["health"])

_GREEN_THRESHOLD  = timedelta(minutes=5)
_YELLOW_THRESHOLD = timedelta(minutes=15)


def _sync_status(last_sync_iso: str | None) -> str:
    if not last_sync_iso:
        return "unknown"
    try:
        last = datetime.fromisoformat(last_sync_iso.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - last
        if age <= _GREEN_THRESHOLD:
            return "green"
        if age <= _YELLOW_THRESHOLD:
            return "yellow"
        return "red"
    except Exception:
        return "unknown"


def _worst(statuses: list[str]) -> str:
    if "red"     in statuses: return "red"
    if "yellow"  in statuses: return "yellow"
    if "green"   in statuses: return "green"
    return "unknown"


@router.get("/dashboard")
def dashboard_health(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return per-service health for the StatusBar component.
    Only checks services relevant to the tenant.
    """
    from app.models.integration import Integration

    services = []

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    wa = db.query(Integration).filter_by(
        tenant_id=current_user.tenant_id, kind="whatsapp_meta"
    ).first()
    if wa:
        status = "red" if wa.status == "error" else (
            _sync_status(wa.last_health_at.isoformat() if wa.last_health_at else None)
            if wa.status == "connected"
            else "unknown"
        )
        services.append({
            "name": "whatsapp",
            "label": "WhatsApp",
            "status": status,
            "last_sync": wa.last_health_at.isoformat() if wa.last_health_at else None,
            "message": wa.error_message if wa.status == "error" else None,
            "reconnect_href": "/dashboard/settings/integrations",
        })

    # ── IVR (CallerDesk / Acefone) ────────────────────────────────────────────
    for kind in ("callerdesk", "acefone"):
        ivr = db.query(Integration).filter_by(
            tenant_id=current_user.tenant_id, kind=kind
        ).first()
        if ivr:
            status = "red" if ivr.status == "error" else (
                _sync_status(ivr.last_health_at.isoformat() if ivr.last_health_at else None)
                if ivr.status == "connected"
                else "unknown"
            )
            services.append({
                "name": kind,
                "label": "IVR" if kind == "callerdesk" else "IVR (Acefone)",
                "status": status,
                "last_sync": ivr.last_health_at.isoformat() if ivr.last_health_at else None,
                "message": ivr.error_message if ivr.status == "error" else None,
                "reconnect_href": "/dashboard/settings/integrations",
            })

    # ── AI / transcription queue ──────────────────────────────────────────────
    # Use Celery inspect — lightweight ping
    try:
        from app.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=1.0)
        active = inspect.active() or {}
        queue_depth = sum(len(v) for v in active.values())
        ai_status = "green" if queue_depth < 20 else ("yellow" if queue_depth < 100 else "red")
    except Exception:
        ai_status = "unknown"
        queue_depth = 0

    services.append({
        "name": "ai",
        "label": "AI",
        "status": ai_status,
        "queue_depth": queue_depth,
        "message": "AI processing queue backed up" if ai_status == "yellow" else (
            "AI queue overloaded" if ai_status == "red" else None
        ),
        "reconnect_href": None,
    })

    # ── Instagram ─────────────────────────────────────────────────────────────
    ig = db.query(Integration).filter_by(
        tenant_id=current_user.tenant_id, kind="instagram"
    ).first()
    if ig:
        status = "red" if ig.status == "error" else (
            _sync_status(ig.last_health_at.isoformat() if ig.last_health_at else None)
            if ig.status == "connected"
            else "unknown"
        )
        services.append({
            "name": "instagram",
            "label": "Instagram",
            "status": status,
            "last_sync": ig.last_health_at.isoformat() if ig.last_health_at else None,
            "message": ig.error_message if ig.status == "error" else None,
            "reconnect_href": "/dashboard/settings/integrations",
        })

    overall = _worst([s["status"] for s in services]) if services else "unknown"

    return {"services": services, "overall": overall}
