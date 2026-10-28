"""Ops GPS (phase 3). Queue: default.

gps.ingest           fixes from the push webhook: store, check trip rules, deliver alerts
gps.tick_all         beat, every minute: fan out to businesses with a GPS connection or a tracker
gps.tick_tenant      poll a pull provider (Traccar), then the rules that need no new fix (tracker silent, long halt)
gps.purge_positions  beat, daily 03:25 IST: delete fixes older than 90 days, one business per transaction
Alert sends are delivered through ops_escalation's delivery (whatsapp queue) after the commit.
"""

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()


def _deliver(tenant_id: str, send_ids: list) -> None:
    from app.workers.tasks.ops_escalation import queue_delivery

    queue_delivery(tenant_id, send_ids)


@shared_task(name="gps.ingest")
def ingest(tenant_id: str, provider: str, positions: list) -> dict:
    from app.services import gps_ingest

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        try:
            out = gps_ingest.ingest(db, tenant_id, provider, [gps_ingest.from_dict(p) for p in positions])
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("gps_ingest_failed", tenant_id=tenant_id, error=str(exc)[:300])
            raise
    _deliver(tenant_id, out.pop("send_ids"))
    return out


@shared_task(name="gps.tick_tenant")
def tick_tenant(tenant_id: str) -> dict:
    from app.services import gps_alerts, gps_ingest

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        try:
            out = gps_ingest.poll(db, tenant_id)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("gps_poll_crashed", tenant_id=tenant_id, error=str(exc)[:300])
            out = {"polled": False}
        sends = out.pop("send_ids", [])
        try:
            sends += gps_alerts.tick(db, tenant_id)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("gps_tick_failed", tenant_id=tenant_id, error=str(exc)[:300])
            raise
    _deliver(tenant_id, sends)
    return {**out, "sends": len(sends)}


def _tenants(db) -> list[str]:
    from app.models.gps import GpsDevice
    from app.models.integration import Integration
    from app.models.tenant import Tenant

    ids = []
    for (tid,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all():
        set_tenant_context(db, tid)  # forced RLS: read each business's rows under its own context
        if (
            db.query(Integration.id).filter_by(tenant_id=tid, kind="gps").first()
            or db.query(GpsDevice.id).filter_by(tenant_id=tid).first()
        ):
            ids.append(tid)
    return ids


@shared_task(name="gps.tick_all")
def tick_all() -> dict:
    with SessionLocal() as db:
        ids = _tenants(db)
    for tid in ids:
        tick_tenant.delay(tid)
    return {"tenants": len(ids)}


@shared_task(name="gps.purge_positions")
def purge_positions() -> dict:
    from app.services import gps_ingest

    total = 0
    with SessionLocal() as db:
        for tid in _tenants(db):
            set_tenant_context(db, tid)
            try:
                total += gps_ingest.purge(db, tid)
                db.commit()
            except Exception as exc:
                db.rollback()
                log.error("gps_purge_failed", tenant_id=tid, error=str(exc)[:300])
    log.info("gps_purge_done", deleted=total)
    return {"deleted": total}
