"""
Backfill guest_events from the sources build_timeline() used to union at
request time: messages, calls, and inquiry_stage_log.

Safe to re-run: record_event() is idempotent on
(tenant_id, entity_type, entity_id, event_type), so replaying overlaps with
live dual-writes without creating duplicates.

    # one tenant
    backfill_guest_events.delay(tenant_id="...")
    # every tenant
    backfill_all_tenants.delay()

Deliberately not on the beat schedule — this is an operator-run migration
task, not routine work.
"""
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.core.database import SessionLocal, set_tenant_context
from app.schemas.guest_events import GuestEventCreate, GuestEventType, SourceModule
from app.services import guest_events_service
import structlog

log = structlog.get_logger()

BATCH = 500


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


@celery_app.task(name="tasks.backfill_guest_events")
def backfill_guest_events(tenant_id: str) -> dict:
    """Populate guest_events for one tenant. Returns per-source counts."""
    from app.models.conversation import Conversation, Message
    from app.models.call import Call
    from app.models.inquiry_360 import InquiryStageLog

    db = SessionLocal()
    counts = {"messages": 0, "calls": 0, "stage_logs": 0}
    try:
        set_tenant_context(db, tenant_id)

        # ── Messages ──────────────────────────────────────────────────────────
        # guest_id/inquiry_id live on the parent conversation, so resolve that
        # map once rather than joining per row.
        conv_map = {
            c.id: (c.guest_id, c.inquiry_id)
            for c in db.query(
                Conversation.id, Conversation.guest_id, Conversation.inquiry_id
            ).filter(Conversation.tenant_id == tenant_id)
        }

        offset = 0
        while True:
            rows = (
                db.query(Message)
                .filter(Message.tenant_id == tenant_id)
                .order_by(Message.created_at)
                .offset(offset).limit(BATCH).all()
            )
            if not rows:
                break
            for m in rows:
                guest_id, inquiry_id = conv_map.get(m.conversation_id, (None, None))
                direction = _enum_val(m.direction)
                body = m.body or ""
                guest_events_service.record_event(
                    db, tenant_id,
                    GuestEventCreate(
                        guest_id=guest_id,
                        inquiry_id=inquiry_id,
                        entity_type="message",
                        entity_id=str(m.id),
                        event_type=(
                            GuestEventType.MESSAGE_SENT
                            if direction == "outbound"
                            else GuestEventType.MESSAGE_RECEIVED
                        ),
                        source_module=SourceModule.INBOX,
                        occurred_at=m.created_at,
                        channel=_enum_val(m.channel),
                        direction=direction,
                        preview=body[:120],
                        is_ai_generated=bool(getattr(m, "is_ai_generated", False)),
                        payload={"conversation_id": m.conversation_id},
                    ),
                )
                counts["messages"] += 1
            db.commit()
            offset += BATCH

        # ── Calls ─────────────────────────────────────────────────────────────
        offset = 0
        while True:
            rows = (
                db.query(Call)
                .filter(Call.tenant_id == tenant_id)
                .order_by(Call.created_at)
                .offset(offset).limit(BATCH).all()
            )
            if not rows:
                break
            for c in rows:
                guest_events_service.record_event(
                    db, tenant_id,
                    GuestEventCreate(
                        guest_id=c.guest_id,
                        inquiry_id=c.inquiry_id,
                        entity_type="call",
                        entity_id=str(c.id),
                        event_type=GuestEventType.CALL_COMPLETED,
                        source_module=SourceModule.CALLS,
                        occurred_at=c.created_at,
                        channel="call",
                        direction=_enum_val(c.direction),
                        preview=(c.ai_summary or "")[:120] or "Call recorded",
                        payload={"ai_summary": c.ai_summary},
                    ),
                )
                counts["calls"] += 1
            db.commit()
            offset += BATCH

        # ── Inquiry stage transitions ─────────────────────────────────────────
        # build_timeline() surfaced only system "merged" rows; the ledger keeps
        # every transition, which is what the Guest Journey view needs.
        offset = 0
        while True:
            rows = (
                db.query(InquiryStageLog)
                .filter(InquiryStageLog.tenant_id == tenant_id)
                .order_by(InquiryStageLog.changed_at)
                .offset(offset).limit(BATCH).all()
            )
            if not rows:
                break
            for sl in rows:
                merged = sl.to_stage == "merged"
                guest_events_service.record_event(
                    db, tenant_id,
                    GuestEventCreate(
                        inquiry_id=sl.inquiry_id,
                        entity_type="inquiry",
                        entity_id=str(sl.id),
                        event_type=(
                            GuestEventType.INQUIRY_MERGED if merged
                            else GuestEventType.INQUIRY_STAGE_MOVED
                        ),
                        source_module=SourceModule.LEADS360,
                        occurred_at=sl.changed_at,
                        channel="system",
                        direction="system",
                        preview=(
                            sl.reason or ("Leads merged" if merged
                                          else f"Stage → {sl.to_stage}")
                        )[:120],
                        actor_user_id=(
                            sl.changed_by
                            if sl.changed_by not in ("system", "ai", None) else None
                        ),
                        payload={
                            "from_stage": sl.from_stage,
                            "to_stage": sl.to_stage,
                            "changed_by": sl.changed_by,
                        },
                    ),
                )
                counts["stage_logs"] += 1
            db.commit()
            offset += BATCH

        log.info("guest_events_backfill_complete", tenant_id=tenant_id, **counts)
        return counts
    finally:
        db.close()


@celery_app.task(name="tasks.backfill_guest_events_all")
def backfill_all_tenants() -> dict:
    """Fan out backfill_guest_events across every tenant."""
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant.id).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        backfill_guest_events.delay(tenant_id=tid)

    log.info("guest_events_backfill_dispatched", tenants=len(tenant_ids))
    return {"tenants_dispatched": len(tenant_ids)}
