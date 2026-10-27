"""Ops alert delivery and the escalation tick (docs/ops/OPS_MODULE_PLAN.md §4). Queue: whatsapp (same as other WA sends).

ops.deliver_sends          deliver queued ops_alert_sends for one tenant; follow-ups from failures are delivered in the same run
ops.escalation_tick        beat, every minute: fan out to tenants with live ops items
ops.escalation_tick_tenant dispatch held items, escalate overdue acks, flag resolve breaches, re-offer stale queued sends
"""

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()

MAX_FOLLOW_UPS = 50


def deliver_now(db, tenant_id: str, send_ids: list[str]) -> int:
    """Deliver sends (and the follow-ups failures produce), committing after each so one bad send can't undo the rest."""
    from app.services import ops_alert_sender

    pending, done = list(send_ids), 0
    while pending and done < MAX_FOLLOW_UPS:
        send_id = pending.pop(0)
        try:
            pending += ops_alert_sender.deliver(db, send_id, tenant_id)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error(
                "ops_deliver_failed",
                tenant_id=tenant_id,
                send_id=send_id,
                error=str(exc),
            )
        done += 1
    if pending:
        log.error("ops_deliver_follow_up_cap", tenant_id=tenant_id, remaining=len(pending))
    return done


def queue_delivery(tenant_id: str, send_ids: list[str]) -> None:
    """Queue delivery after the caller's commit. A lost queue message is picked up by the tick (stale queued sends)."""
    if not send_ids:
        return
    try:
        deliver_sends.apply_async(args=[tenant_id, list(send_ids)], countdown=1)
    except Exception as exc:
        log.error("ops_queue_delivery_failed", tenant_id=tenant_id, error=str(exc))


@shared_task(name="ops.deliver_sends")
def deliver_sends(tenant_id: str, send_ids: list) -> dict:
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return {"delivered": deliver_now(db, tenant_id, list(send_ids))}
    finally:
        db.close()


@shared_task(name="ops.escalation_tick_tenant")
def escalation_tick_tenant(tenant_id: str) -> dict:
    from app.services import ops_escalation_service

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        send_ids = ops_escalation_service.tick(db, tenant_id)
        db.commit()
        delivered = deliver_now(db, tenant_id, send_ids)
        return {"sends": len(send_ids), "delivered": delivered}
    finally:
        db.close()


@shared_task(name="ops.escalation_tick")
def escalation_tick() -> dict:
    """Beat, every minute. Only tenants that have an open or acknowledged ops item get a tick."""
    from app.models.ops import OpsItem
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        tenant_ids = [t for (t,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all()]
        live = []
        for tid in tenant_ids:
            set_tenant_context(db, tid)
            if (
                db.query(OpsItem.id)
                .filter(
                    OpsItem.tenant_id == tid,
                    OpsItem.status.in_(("open", "acknowledged")),
                )
                .first()
                is not None
            ):
                live.append(tid)
    finally:
        db.close()
    for tid in live:
        escalation_tick_tenant.delay(tid)
    return {"tenants": len(live)}
