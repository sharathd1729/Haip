"""
X8 — Dashboard health endpoint.

Returns per-integration health for the status bar.
Health per integration comes from services/integration_health.py (one rule shared with the
Integrations page and the D3 insight). The AI row reports Celery queue depth:
  green < 20 active tasks, yellow < 100, red beyond, unknown if the broker cannot be asked.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/health", tags=["health"])

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
    from app.services import integration_health

    services = []

    # ── Integrations ──────────────────────────────────────────────────────────
    # Same rule the Integrations page and the D3 insight use (services/integration_health.py):
    # a connected channel is healthy; only an errored one, or a stale polled PMS sync, is not.
    # Channels the owner has not connected or has turned off are not faults and are not listed.
    rows = db.query(Integration).filter(Integration.tenant_id == current_user.tenant_id).all()
    for row in sorted(rows, key=lambda r: r.kind):
        health = integration_health.classify(row.kind, row.status, row.last_health_at)
        if health == integration_health.OFF:
            continue
        services.append({
            "name": row.kind,
            "label": integration_health.label(row.kind),
            "status": health,
            "last_sync": row.last_health_at if row.last_health_at else None,
            "message": (row.config or {}).get("last_error") if health == integration_health.RED else None,
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

    overall = _worst([s["status"] for s in services]) if services else "unknown"

    return {"services": services, "overall": overall}
