"""
Celery task: generate (upsert) dashboard widget snapshots.

Called:
  - Daily via beat schedule (tenant_id="__all__")
  - After call_processed / message_received events (specific tenant + keys)
  - On POST /dashboard/widgets/refresh (single widget)
"""

import structlog
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.widget_service import (
    WIDGET_REGISTRY, detect_modules, upsert_widget,
)

log = structlog.get_logger()


@shared_task(name="tasks.generate_widgets", bind=True, max_retries=2, default_retry_delay=60)
def generate_widgets(
    self,
    tenant_id: str,
    widget_keys: list[str] | None = None,
    range_days: int = 30,
):
    """
    Upsert widget snapshots for one tenant or all active tenants.

    tenant_id="__all__"  → iterate every active tenant
    widget_keys=None     → regenerate all 18 widgets
    widget_keys=[...]    → regenerate only those keys
    """
    db: Session = SessionLocal()
    try:
        if tenant_id == "__all__":
            tenants = db.query(Tenant).filter(Tenant.is_active.is_(True)).all()
        else:
            tenants = db.query(Tenant).filter(Tenant.id == tenant_id).all()

        keys = widget_keys or list(WIDGET_REGISTRY.keys())

        for tenant in tenants:
            modules = detect_modules(db, tenant)
            for key in keys:
                try:
                    upsert_widget(db, tenant, key, modules, range_days)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "widget_upsert_failed",
                        tenant=tenant.id,
                        widget=key,
                        error=str(exc),
                    )
            db.commit()
            log.info("widgets_generated", tenant=tenant.id, count=len(keys))

    except Exception as exc:
        db.rollback()
        log.error("generate_widgets_task_failed", error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
