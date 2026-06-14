"""
Celery beat task — fires time-based automation triggers every 30 minutes.

Handles:
  no_response_2h     inquiry open + last inbound message > 2h ago, no outbound reply
  no_response_24h    same but > 24h
  stay_check_in_1d   guest check-in date is tomorrow
  stay_check_out_1d  guest check-out date is tomorrow
"""
from datetime import datetime, timezone, timedelta
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
import structlog

log = structlog.get_logger()


@celery_app.task(name="tasks.check_automation_timers.run")
def run():
    """Fan out — check all tenants that have timer-based rules active."""
    from app.models.automation import AutomationRule

    db = SessionLocal()
    try:
        timer_triggers = {
            "no_response_2h", "no_response_24h",
            "stay_check_in_1d", "stay_check_out_1d",
        }
        tenant_ids = [
            row[0] for row in
            db.query(AutomationRule.tenant_id)
            .filter(
                AutomationRule.is_active == True,
                AutomationRule.trigger.in_(timer_triggers),
            )
            .distinct()
            .all()
        ]
        for tid in tenant_ids:
            check_tenant.apply_async(kwargs={"tenant_id": tid}, queue="whatsapp")
        log.info("check_automation_timers_fanned_out", tenant_count=len(tenant_ids))
    finally:
        db.close()


@celery_app.task(name="tasks.check_automation_timers.check_tenant")
def check_tenant(tenant_id: str):
    from app.core.database import set_tenant_context
    from app.models.automation import AutomationRule
    from app.workers.tasks.automation_engine import fire_trigger

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        now = datetime.now(timezone.utc)

        rules = (
            db.query(AutomationRule)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .filter(AutomationRule.trigger.in_({
                "no_response_2h", "no_response_24h",
                "stay_check_in_1d", "stay_check_out_1d",
            }))
            .all()
        )

        has_no_resp_2h = any(r.trigger == "no_response_2h"   for r in rules)
        has_no_resp_24 = any(r.trigger == "no_response_24h"  for r in rules)
        has_checkin    = any(r.trigger == "stay_check_in_1d"  for r in rules)
        has_checkout   = any(r.trigger == "stay_check_out_1d" for r in rules)

        # ── no_response timers ─────────────────────────────────────────────
        if has_no_resp_2h or has_no_resp_24:
            _fire_no_response(db, tenant_id, now, has_no_resp_2h, has_no_resp_24)

        # ── stay check-in / check-out ──────────────────────────────────────
        if has_checkin or has_checkout:
            _fire_stay_reminders(db, tenant_id, now, has_checkin, has_checkout)

    finally:
        db.close()


def _fire_no_response(db, tenant_id: str, now: datetime,
                      fire_2h: bool, fire_24h: bool):
    """
    Find open conversations with no outbound message after threshold.
    Uses automation_runs as a dedup guard (one fire per conversation per day).
    """
    from app.models.conversation import Conversation, Message, MessageDirection
    from app.models.automation import AutomationRun
    from app.workers.tasks.automation_engine import fire_trigger

    open_convs = (
        db.query(Conversation)
        .filter_by(tenant_id=tenant_id, is_open=True)
        .all()
    )
    for conv in open_convs:
        # Find last inbound and last outbound message times
        last_inbound = (
            db.query(Message.created_at)
            .filter_by(conversation_id=conv.id, direction=MessageDirection.INBOUND)
            .order_by(Message.created_at.desc())
            .scalar()
        )
        if not last_inbound:
            continue

        last_outbound = (
            db.query(Message.created_at)
            .filter_by(conversation_id=conv.id, direction=MessageDirection.OUTBOUND)
            .order_by(Message.created_at.desc())
            .scalar()
        )

        # If there's a recent outbound, no trigger needed
        if last_outbound and last_outbound >= last_inbound:
            continue

        # Make timezone-aware if naive
        if last_inbound.tzinfo is None:
            last_inbound = last_inbound.replace(tzinfo=timezone.utc)

        age_hours = (now - last_inbound).total_seconds() / 3600

        context = {
            "conversation_id": str(conv.id),
            "guest_id": str(conv.guest_id) if conv.guest_id else None,
        }

        if fire_24h and age_hours >= 24:
            dedup_key = f"no_response_24h:{conv.id}:{now.strftime('%Y-%m-%d')}"
            if not _already_ran_today(db, tenant_id, "no_response_24h", conv.id, now):
                fire_trigger.apply_async(
                    kwargs={"event": "no_response_24h", "tenant_id": tenant_id, "context": context},
                    queue="whatsapp",
                )
        elif fire_2h and age_hours >= 2:
            if not _already_ran_today(db, tenant_id, "no_response_2h", conv.id, now):
                fire_trigger.apply_async(
                    kwargs={"event": "no_response_2h", "tenant_id": tenant_id, "context": context},
                    queue="whatsapp",
                )


def _fire_stay_reminders(db, tenant_id: str, now: datetime,
                         fire_checkin: bool, fire_checkout: bool):
    """
    Find bookings whose check_in / check_out is tomorrow.
    """
    from app.models.inquiry import Inquiry
    from app.workers.tasks.automation_engine import fire_trigger

    tomorrow = (now + timedelta(days=1)).date()
    inquiries = db.query(Inquiry).filter_by(tenant_id=tenant_id).all()

    for inq in inquiries:
        context = {
            "inquiry_id": str(inq.id),
            "guest_id": str(inq.guest_id) if inq.guest_id else None,
        }
        if fire_checkin and inq.check_in and inq.check_in == tomorrow:
            if not _already_ran_today(db, tenant_id, "stay_check_in_1d", inq.id, now):
                fire_trigger.apply_async(
                    kwargs={"event": "stay_check_in_1d", "tenant_id": tenant_id, "context": context},
                    queue="whatsapp",
                )
        if fire_checkout and inq.check_out and inq.check_out == tomorrow:
            if not _already_ran_today(db, tenant_id, "stay_check_out_1d", inq.id, now):
                fire_trigger.apply_async(
                    kwargs={"event": "stay_check_out_1d", "tenant_id": tenant_id, "context": context},
                    queue="whatsapp",
                )


def _already_ran_today(db, tenant_id: str, event: str, entity_id: str, now: datetime) -> bool:
    """Dedup guard — return True if this event+entity already fired today."""
    from app.models.automation import AutomationRun
    from sqlalchemy import func

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    existing = (
        db.query(AutomationRun)
        .filter(
            AutomationRun.tenant_id == tenant_id,
            AutomationRun.trigger_event == event,
            AutomationRun.ran_at >= today_start,
            AutomationRun.context.op("->>")(
                "inquiry_id" if "stay" in event else "conversation_id"
            ) == entity_id,
        )
        .first()
    )
    return existing is not None
