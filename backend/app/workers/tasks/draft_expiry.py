"""Beat sweep: AI drafts nobody acted on are closed as "expired" (rules and why: services/ai_draft_expiry.py)."""
import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="ai_drafts.expire_stale")
def expire_stale(tenant_id: str) -> dict:
    from app.services import ai_draft_expiry

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        expired = ai_draft_expiry.sweep(db, tenant_id)
        db.commit()
        return {"expired": expired}
    finally:
        db.close()


@shared_task(name="ai_drafts.expire_stale_all_tenants")
def expire_stale_all_tenants() -> dict:
    """Fan out to every active tenant, one transaction each (beat, every 30 minutes)."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    for tid in tenant_ids:
        expire_stale.delay(tid)
    return {"tenants_queued": len(tenant_ids)}
