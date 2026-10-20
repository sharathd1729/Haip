"""Celery side of the lead workflows (services: lead_playbook_engine, lead_journey_tracker).

  lead_playbooks.on_call            call ingest queues it ~45 s after a call is logged (and wrap-up/scoring re-queue it when a
                                    call turns out to be voicemail/no answer): runs P1 missed call / P2 no answer
  lead_playbooks.on_callback_tap    the WhatsApp webhook queues it when a guest taps "Call me back" on a playbook message
  lead_playbooks.drain_due          beat, every minute: runs whose time has come (safety net for a lost on_call)
  lead_journey.sweep_all_tenants    beat, every 5 minutes: fan out lead_journey.sweep_tenant
  lead_journey.sweep_tenant         refresh the journey milestones of recent enquiries

All on exact-name routes (celery_app.py): the playbook tasks on "whatsapp" (they queue WhatsApp sends), the sweep on
"default". None of them retries a step that may already have sent a message.
"""
import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = structlog.get_logger()

# How long after a call is logged the playbook looks at it: lets an agent's instant redial land first and the IVR's
# dial status settle. The guards re-check everything when the step fires.
CALL_DELAY_SECONDS = 45


def queue_on_call(tenant_id: str, call_id: str, countdown: int = CALL_DELAY_SECONDS) -> None:
    """Best-effort enqueue from ingest code: a broker hiccup must never fail the call ingest."""
    try:
        on_call.apply_async(kwargs={"tenant_id": tenant_id, "call_id": call_id}, countdown=countdown)
    except Exception as exc:  # noqa: BLE001
        log.warning("playbook_on_call_enqueue_failed", tenant_id=tenant_id, call_id=call_id, error=str(exc)[:200])


@shared_task(name="lead_playbooks.on_call")
def on_call(tenant_id: str, call_id: str) -> dict:
    from app.services import lead_playbook_engine as engine
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        out = engine.on_call(db, tenant_id, call_id)
        log.info("playbook_on_call", tenant_id=tenant_id, call_id=call_id, **{k: v for k, v in out.items() if k != "reason"})
        return out
    finally:
        db.close()


@shared_task(name="lead_playbooks.on_callback_tap")
def on_callback_tap(tenant_id: str, guest_id: str, inquiry_id: str | None, wa_msg_id: str, button_text: str) -> dict:
    from app.services import lead_playbook_engine as engine
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        return engine.on_callback_tap(db, tenant_id, guest_id, inquiry_id, wa_msg_id, button_text)
    finally:
        db.close()


@shared_task(name="lead_playbooks.drain_due")
def drain_due() -> dict:
    from app.services import lead_playbook_engine as engine
    db = SessionLocal()
    try:
        return {"ran": engine.drain_due(db)}
    finally:
        db.close()


@shared_task(name="lead_journey.sweep_tenant")
def sweep_tenant(tenant_id: str) -> dict:
    from app.services import lead_journey_tracker as journey
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        out = journey.sweep_tenant(db, tenant_id)
        db.commit()
        return out
    except Exception:
        db.rollback()
        log.exception("lead_journey_sweep_failed", tenant_id=tenant_id)
        raise
    finally:
        db.close()


@shared_task(name="lead_journey.sweep_all_tenants")
def sweep_all_tenants() -> dict:
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    for tid in tenant_ids:
        sweep_tenant.delay(tid)
    return {"tenants_queued": len(tenant_ids)}
