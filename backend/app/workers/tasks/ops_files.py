"""Ops files housekeeping. Queue: default.

ops.sync_files_all     beat, daily 06:10 IST: fan out to every business whose category has an ops pack
ops.sync_files_tenant  open a file for each live booking that has none; mark files of cancelled bookings (ops_trip_service.sync_files)
Reading Ops today runs the same sync, so a booking confirmed mid-day appears as soon as someone looks.

ops.auto_messages_all     beat, hourly at :25: fan out (queue whatsapp)
ops.auto_messages_tenant  crew brief / photo reminder / guest pre-trip / deposit reminder (ops_auto_messages) + keep open
                          critical defects' calendar blocks rolling (ops_fleet_service.keep_blocks)
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
    from app.services import booking_agenda_service, ops_pack_seed, ops_trip_service

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        try:
            ops_pack_seed.seed(db, tenant_id)  # a business that predates its pack gets it here (insert-only)
            out = ops_trip_service.sync_files(db, tenant_id, booking_agenda_service.tenant_today(db, tenant_id))
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("ops_sync_files_failed", tenant_id=tenant_id, error=str(exc)[:300])
            raise
    log.info("ops_sync_files_done", tenant_id=tenant_id, **out)
    return out


@shared_task(name="ops.auto_messages_all")
def auto_messages_all():
    """Hourly: the automatic trip messages (ops_auto_messages) and the defect blocks, for every business with an ops pack."""
    from app.models.tenant import Tenant
    from app.services import ops_pack_catalog as packs

    with SessionLocal() as db:
        ids = [t.id for t in db.query(Tenant.id, Tenant.business_type) if packs.pack_for_business_type(t.business_type)]
    for tenant_id in ids:
        auto_messages_tenant.delay(tenant_id)
    return len(ids)


@shared_task(name="ops.auto_messages_tenant")
def auto_messages_tenant(tenant_id: str):
    from app.services import booking_agenda_service, ops_auto_messages, ops_fleet_service
    from app.workers.tasks.ops_escalation import queue_delivery

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        try:
            blocks = ops_fleet_service.keep_blocks(db, tenant_id, booking_agenda_service.tenant_today(db, tenant_id))
            db.commit()
            sends = ops_auto_messages.run_tenant(db, tenant_id)
        except Exception as exc:
            db.rollback()
            log.error("ops_auto_messages_failed", tenant_id=tenant_id, error=str(exc)[:300])
            raise
    queue_delivery(tenant_id, sends)
    log.info("ops_auto_messages_done", tenant_id=tenant_id, alerts=len(sends), blocks=blocks)
    return {"alerts": len(sends), "blocks": blocks}
