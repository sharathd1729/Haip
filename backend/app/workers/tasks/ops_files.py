"""Ops files housekeeping. Queue: default.

ops.sync_files_all     beat, daily 06:10 IST: fan out to every business whose category has an ops pack
ops.sync_files_tenant  open a file for each live booking that has none; mark files of cancelled bookings (ops_trip_service.sync_files)
Reading Ops today runs the same sync, so a booking confirmed mid-day appears as soon as someone looks.
"""

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()


@shared_task(name="ops.sync_files_all")
def sync_files_all():
    from app.models.tenant import Tenant
    from app.services import ops_pack_catalog as packs

    with SessionLocal() as db:
        ids = [t.id for t in db.query(Tenant.id, Tenant.business_type) if packs.pack_for_business_type(t.business_type)]
    for tenant_id in ids:
        sync_files_tenant.delay(tenant_id)
    log.info("ops_sync_files_fanout", tenants=len(ids))
    return len(ids)


@shared_task(name="ops.sync_files_tenant")
def sync_files_tenant(tenant_id: str):
    from app.services import booking_agenda_service, ops_trip_service

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        try:
            out = ops_trip_service.sync_files(db, tenant_id, booking_agenda_service.tenant_today(db, tenant_id))
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("ops_sync_files_failed", tenant_id=tenant_id, error=str(exc)[:300])
            raise
    log.info("ops_sync_files_done", tenant_id=tenant_id, **out)
    return out
