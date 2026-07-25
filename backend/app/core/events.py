"""
emit_event() — the one call site for "something happened to a guest".

Before this existed, a code path that mattered had to remember to do three
unrelated things by hand: fire the automation trigger, append to whatever
timeline the feature used, and write an audit row. They were wired
independently in ~31 places, so they drifted.

    from app.core.events import emit_event

    emit_event(
        db,
        tenant_id=tenant_id,
        event_type=GuestEventType.MESSAGE_RECEIVED,
        entity_type="message", entity_id=msg.id,
        source_module=SourceModule.INBOX,
        occurred_at=msg.created_at,
        guest_id=guest_id, inquiry_id=inquiry_id,
        channel="whatsapp", direction="inbound", preview=body[:120],
        automation_trigger="new_inquiry",   # optional
        audit_action="message.received",    # optional
    )

New code should call this instead of hand-wiring the three concerns. Existing
call sites migrate opportunistically — this does not require a mass refactor.

Ordering note: the ledger write happens first and the automation trigger is
dispatched last, so a Celery worker that picks the task up immediately always
sees the event already recorded.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session
import structlog

from app.core.audit import append_audit
from app.schemas.guest_events import GuestEventCreate
from app.services import guest_events_service

log = structlog.get_logger()


def emit_event(
    db: Session,
    *,
    tenant_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    source_module: str,
    occurred_at: datetime,
    guest_id: Optional[str] = None,
    inquiry_id: Optional[str] = None,
    channel: Optional[str] = None,
    direction: Optional[str] = None,
    preview: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    is_ai_generated: bool = False,
    payload: Optional[dict[str, Any]] = None,
    automation_trigger: Optional[str] = None,
    automation_context: Optional[dict[str, Any]] = None,
    audit_action: Optional[str] = None,
    commit: bool = False,
) -> None:
    """
    Record an event and fan out to automation + audit.

    Only `automation_trigger` and `audit_action` opt into those side effects —
    a plain message arriving is ledger-only; a stage change is all three.

    The caller owns the transaction: pass commit=True only if this is the last
    write in the unit of work.
    """
    payload = payload or {}

    guest_events_service.record_event(
        db,
        tenant_id,
        GuestEventCreate(
            guest_id=guest_id,
            inquiry_id=inquiry_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            source_module=source_module,
            occurred_at=occurred_at,
            channel=channel,
            direction=direction,
            preview=preview,
            actor_user_id=actor_user_id,
            is_ai_generated=is_ai_generated,
            payload=payload,
        ),
    )

    if audit_action:
        append_audit(
            db,
            tenant_id=tenant_id,
            action=audit_action,
            actor_user_id=actor_user_id,
            target_type=entity_type,
            target_id=entity_id,
            payload={"event_type": event_type, **payload},
        )

    if commit:
        db.commit()

    # Dispatched last: the task must not race ahead of the rows above.
    if automation_trigger:
        try:
            from app.workers.tasks.automation_engine import fire_trigger

            ctx = {"guest_id": guest_id, "inquiry_id": inquiry_id}
            ctx.update(automation_context or {})
            fire_trigger.delay(
                event=automation_trigger, tenant_id=tenant_id, context=ctx
            )
        except Exception:
            # A broker hiccup must not roll back an event that already happened.
            log.exception(
                "emit_event_automation_dispatch_failed",
                tenant_id=tenant_id,
                trigger=automation_trigger,
                entity_id=entity_id,
            )
