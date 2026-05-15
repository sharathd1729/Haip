"""
Broadcast tasks that fan out per-tenant PMS syncs.
These are called by Celery Beat on a schedule.
Each task queries all active integrations of the given kind
and fires one sync task per tenant.
"""

from __future__ import annotations
import logging
from celery import shared_task
from app.core.database import SessionLocal
from app.models.integration import Integration

logger = logging.getLogger(__name__)


@shared_task(name="sync_retalwise_all_tenants")
def sync_retalwise_all_tenants() -> dict:
    """Fire sync_retalwise for every tenant that has an active RentalWise integration."""
    db = SessionLocal()
    try:
        rows = db.query(Integration).filter_by(kind="retalwise", status="active").all()
        tenant_ids = [r.tenant_id for r in rows]
    finally:
        db.close()

    if not tenant_ids:
        return {"queued": 0}

    from app.workers.tasks.sync_retalwise import sync_retalwise
    for tenant_id in tenant_ids:
        sync_retalwise.delay(tenant_id)
        logger.info("Queued RentalWise sync for tenant %s", tenant_id)

    return {"queued": len(tenant_ids)}


@shared_task(name="sync_hostaway_all_tenants")
def sync_hostaway_all_tenants() -> dict:
    """Fire sync_hostaway for every tenant that has an active Hostaway integration."""
    db = SessionLocal()
    try:
        rows = db.query(Integration).filter_by(kind="hostaway", status="active").all()
        tenant_ids = [r.tenant_id for r in rows]
    finally:
        db.close()

    if not tenant_ids:
        return {"queued": 0}

    from app.workers.tasks.sync_hostaway import sync_hostaway
    for tenant_id in tenant_ids:
        sync_hostaway.delay(tenant_id)
        logger.info("Queued Hostaway sync for tenant %s", tenant_id)

    return {"queued": len(tenant_ids)}
