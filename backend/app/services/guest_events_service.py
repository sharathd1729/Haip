"""
Guest event ledger — service layer.

The only place that writes to or reads from `guest_events`. Callers should not
construct GuestEvent rows directly; go through record_event() (or, for anything
that is also an automation trigger / audit-worthy state change, through
app.core.events.emit_event, which wraps this).

Writes are idempotent: the (tenant_id, entity_type, entity_id, event_type)
unique constraint means replaying the same source row is a no-op, so the
backfill can be re-run safely alongside live dual-writes.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import structlog

from app.models.guest_event import GuestEvent
from app.models.base import gen_uuid
from app.schemas.guest_events import GuestEventCreate, GuestEventSchema

log = structlog.get_logger()

# Matches leads_service.TIMELINE_CAP — the V1 cap on timeline length.
TIMELINE_CAP = 50


def record_event(
    db: Session,
    tenant_id: str,
    event: GuestEventCreate,
    *,
    commit: bool = False,
) -> Optional[GuestEvent]:
    """
    Append one event to the ledger. Idempotent on
    (tenant_id, entity_type, entity_id, event_type).

    Returns the inserted row, or None when the event already existed.

    The insert runs inside a SAVEPOINT so that a duplicate raises IntegrityError
    against the savepoint only. Without it, Postgres would abort the *enclosing*
    transaction and every subsequent write in the caller's unit of work would
    fail — the same failure mode documented for alembic's env.py in CLAUDE.md.
    This also keeps the write dialect-agnostic (the test suite runs on SQLite).
    """
    row = GuestEvent(
        id=gen_uuid(),
        tenant_id=tenant_id,
        guest_id=event.guest_id,
        inquiry_id=event.inquiry_id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        event_type=event.event_type,
        source_module=event.source_module,
        occurred_at=event.occurred_at,
        channel=event.channel,
        direction=event.direction,
        preview=event.preview or None,
        actor_user_id=event.actor_user_id,
        is_ai_generated=event.is_ai_generated,
        payload=event.payload or {},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    try:
        with db.begin_nested():
            db.add(row)
            # Scoped to `row`: a bare flush() would also flush whatever else the
            # caller has pending, so an unrelated broken object in their unit of
            # work would surface here and poison the session — breaking this
            # function's contract of never disrupting its caller.
            db.flush([row])
    except IntegrityError:
        # Already recorded — replaying a source row is a no-op by design.
        log.debug(
            "guest_event_duplicate_ignored",
            tenant_id=tenant_id, entity_type=event.entity_type,
            entity_id=event.entity_id, event_type=event.event_type,
        )
        return None

    if commit:
        db.commit()
    return row


def get_guest_timeline(
    db: Session,
    tenant_id: str,
    guest_id: str,
    limit: int = TIMELINE_CAP,
) -> tuple[list[GuestEventSchema], bool]:
    """
    Guest-level journey: every event for this guest across all inquiries,
    newest first. Returns (entries, capped).

    This is the read the old per-inquiry timeline could not do at all.
    """
    rows = (
        db.query(GuestEvent)
        .filter(GuestEvent.tenant_id == tenant_id, GuestEvent.guest_id == guest_id)
        .order_by(desc(GuestEvent.occurred_at))
        .limit(limit + 1)
        .all()
    )
    capped = len(rows) > limit
    return [GuestEventSchema.model_validate(r) for r in rows[:limit]], capped


def get_inquiry_timeline(
    db: Session,
    tenant_id: str,
    inquiry_id: str,
    limit: int = TIMELINE_CAP,
) -> tuple[list[GuestEventSchema], bool]:
    """
    Inquiry-scoped timeline — the ledger-backed equivalent of
    leads_service.build_timeline(). Same cap semantics.
    """
    rows = (
        db.query(GuestEvent)
        .filter(GuestEvent.tenant_id == tenant_id, GuestEvent.inquiry_id == inquiry_id)
        .order_by(desc(GuestEvent.occurred_at))
        .limit(limit + 1)
        .all()
    )
    capped = len(rows) > limit
    return [GuestEventSchema.model_validate(r) for r in rows[:limit]], capped


def attach_guest(db: Session, tenant_id: str, from_guest_id: str, to_guest_id: str) -> int:
    """
    Re-point events from one GID to another. Called after identity_service
    merges two guests, so the surviving GID's journey stays complete.

    Returns the number of rows moved.
    """
    moved = (
        db.query(GuestEvent)
        .filter(GuestEvent.tenant_id == tenant_id, GuestEvent.guest_id == from_guest_id)
        .update({"guest_id": to_guest_id}, synchronize_session=False)
    )
    log.info(
        "guest_events_reattached",
        tenant_id=tenant_id, from_guest=from_guest_id, to_guest=to_guest_id, moved=moved,
    )
    return moved
