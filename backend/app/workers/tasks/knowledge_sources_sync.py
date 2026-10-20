"""Celery: read Instagram posts, running ads and the tenant's website into the knowledge base (services/knowledge_sources.py,
services/knowledge_freshness.py). Beat entries in celery_app.py: "knowledge-social-sync-4h", "knowledge-website-recrawl-weekly".
Exact-name routes (queue ai_scoring) are required by tests/test_celery_task_routing.py."""
import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()


def _active_tenants(db):
    from app.models.tenant import Tenant
    return db.query(Tenant).filter(Tenant.is_active.is_(True)).all()


@shared_task(name="knowledge_sources.sync_all_tenants")
def sync_all_tenants():
    """Fan out to every active tenant whose knowledge settings allow the social sync (default on: entries arrive pending)."""
    from app.services import knowledge_sources
    db = SessionLocal()
    try:
        ids = [t.id for t in _active_tenants(db) if knowledge_sources.settings(t)["social_sync"]]
    finally:
        db.close()
    for tid in ids:
        sync_tenant.apply_async(kwargs={"tenant_id": tid})
    return {"tenants_queued": len(ids)}


@shared_task(name="knowledge_sources.sync_tenant")
def sync_tenant(tenant_id: str):
    from app.models.tenant import Tenant
    from app.services import knowledge_sources
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None or not knowledge_sources.settings(tenant)["social_sync"]:
            return {"status": "skipped"}
        out = {}
        for label, fn in (("instagram", knowledge_sources.sync_instagram), ("meta_ad", knowledge_sources.sync_meta_ads)):
            try:
                out[label] = fn(db, tenant)
            except Exception as exc:  # noqa: BLE001 -- one source failing must not stop the other
                db.rollback()
                log.error("kb_social_sync_failed", tenant_id=tenant_id, source=label, error=str(exc)[:300])
                out[label] = {"status": "error"}
        return out
    finally:
        db.close()


@shared_task(name="knowledge_sources.recrawl_all_tenants")
def recrawl_all_tenants():
    """Weekly: only tenants that switched on brand_config.knowledge.website_recrawl (default off)."""
    from app.services import knowledge_sources
    db = SessionLocal()
    try:
        ids = [t.id for t in _active_tenants(db) if knowledge_sources.settings(t)["website_recrawl"]]
    finally:
        db.close()
    for tid in ids:
        recrawl_tenant.apply_async(kwargs={"tenant_id": tid})
    return {"tenants_queued": len(ids)}


@shared_task(name="knowledge_sources.recrawl_tenant")
def recrawl_tenant(tenant_id: str):
    from app.services import knowledge_freshness
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return knowledge_freshness.recrawl_website(db, tenant_id)
    finally:
        db.close()
