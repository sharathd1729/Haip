"""Inquiry pipeline service — with state-machine transition validation."""
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.user import UserRole
import structlog

log = structlog.get_logger()

# Leads360 restructure Phase 1: legacy enum member -> pipeline_stages.key.
# GHOSTED groups under the same "Closed" stage as LOST (CLAUDE.md); the
# deprecated SITE_VISIT alias maps to site_visit_scheduled.
_ENUM_TO_STAGE_KEY: dict[InquiryStage, str] = {
    InquiryStage.NEW: "new",
    InquiryStage.RESPONDING: "responding",
    InquiryStage.QUOTED: "quoted",
    InquiryStage.SITE_VISIT: "site_visit_scheduled",
    InquiryStage.SITE_VISIT_SCHEDULED: "site_visit_scheduled",
    InquiryStage.SITE_VISIT_DONE: "site_visit_done",
    InquiryStage.BOOKED: "booked",
    InquiryStage.LOST: "closed",
    InquiryStage.GHOSTED: "closed",
}


def _stage_id_for(db: Session, tenant_id: str, stage: InquiryStage) -> Optional[str]:
    """Resolve the pipeline_stages row matching a legacy enum value, for
    keeping stage_id in sync while call sites are migrated incrementally.
    Best-effort: stage_id is a Phase 1 migration aid, not yet load-bearing
    for any transition logic, so a lookup failure must never block the
    actual enum-based stage change (same pattern as the audit/stage-log
    writes below)."""
    key = _ENUM_TO_STAGE_KEY.get(stage)
    if not key:
        return None
    try:
        row = (
            db.query(PipelineStage.id)
            .filter_by(tenant_id=tenant_id, key=key)
            .first()
        )
        return row[0] if row else None
    except Exception as exc:
        log.warning("stage_id_sync_failed", tenant_id=tenant_id, stage=stage.value, error=str(exc))
        return None


# ── State machine ─────────────────────────────────────────────────────────────

#: Ranks for detecting backward moves (exit stages have no rank).
_STAGE_RANK: dict[InquiryStage, int] = {
    InquiryStage.NEW:                  0,
    InquiryStage.RESPONDING:           1,
    InquiryStage.QUOTED:               2,
    InquiryStage.SITE_VISIT:           3,   # deprecated alias — kept for compat
    InquiryStage.SITE_VISIT_SCHEDULED: 3,   # Leads360 addition
    InquiryStage.SITE_VISIT_DONE:      4,   # Leads360 addition
    InquiryStage.BOOKED:               5,
}

#: Allowed *forward* transitions per stage (excluding exit stages).
ALLOWED_FORWARD: dict[InquiryStage, set[InquiryStage]] = {
    InquiryStage.NEW:        {InquiryStage.RESPONDING},
    InquiryStage.RESPONDING: {InquiryStage.QUOTED},
    InquiryStage.QUOTED:     {
        InquiryStage.SITE_VISIT_SCHEDULED,  # new path
        InquiryStage.SITE_VISIT,            # backward-compat
        InquiryStage.BOOKED,
    },
    InquiryStage.SITE_VISIT_SCHEDULED: {InquiryStage.SITE_VISIT_DONE},
    InquiryStage.SITE_VISIT_DONE:      {InquiryStage.BOOKED},
    InquiryStage.SITE_VISIT:           {InquiryStage.BOOKED},   # deprecated compat
    InquiryStage.BOOKED:               set(),
    InquiryStage.LOST:                 set(),
    InquiryStage.GHOSTED:              set(),
}

#: Terminal exit stages — reachable from *any* non-terminal stage.
EXIT_STAGES: set[InquiryStage] = {InquiryStage.LOST, InquiryStage.GHOSTED}

#: Roles allowed to perform backward transitions.
BACKWARD_ROLES: set[str] = {UserRole.OWNER.value, UserRole.MANAGER.value}


class InvalidStageTransition(Exception):
    """Raised when a stage transition is not allowed by the state machine."""
    def __init__(self, from_stage: str, to_stage: str, reason: str = ""):
        self.from_stage = from_stage
        self.to_stage = to_stage
        self.detail = reason or f"Cannot transition inquiry from '{from_stage}' to '{to_stage}'"
        super().__init__(self.detail)


def _is_backward(from_stage: InquiryStage, to_stage: InquiryStage) -> bool:
    """True when to_stage has a lower pipeline rank than from_stage."""
    return (
        from_stage in _STAGE_RANK
        and to_stage in _STAGE_RANK
        and _STAGE_RANK[to_stage] < _STAGE_RANK[from_stage]
    )


# ── Public service functions ──────────────────────────────────────────────────

def get_or_create(db: Session, tenant_id: str, guest_id: str, source: str = "phone") -> Inquiry:
    """Find the most recent open inquiry for a guest, or create one."""
    closed_stages = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
    inquiry = (
        db.query(Inquiry)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .filter(~Inquiry.stage.in_(closed_stages))
        .order_by(Inquiry.created_at.desc())
        .first()
    )
    if not inquiry:
        try:
            src = InquirySource(source)
        except ValueError:
            src = InquirySource.PHONE
        inquiry = Inquiry(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            guest_id=guest_id,
            stage=InquiryStage.NEW,
            stage_id=_stage_id_for(db, tenant_id, InquiryStage.NEW),
            source=src,
        )
        db.add(inquiry)
        db.flush()
        log.info("inquiry_created", inquiry_id=inquiry.id, guest_id=guest_id)
    return inquiry


def get_or_create_from_chat(
    db: Session, tenant_id: str, guest_id: str, *, source: str, message_text: str,
) -> Inquiry:
    """
    Leads360 chat auto-create (WhatsApp/Instagram) -- same open-inquiry
    lookup as get_or_create(), but a freshly created inquiry is routed to
    a tenant-tagged pipeline stage (migration 048) based on the message
    content, instead of always landing in the legacy NEW enum stage.
    See app/services/lead_auto_create.py for the routing rules.
    """
    from app.services.lead_auto_create import (
        is_collab_message, text_contains_phone, resolve_entry_stage_id,
    )

    closed_stages = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
    inquiry = (
        db.query(Inquiry)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .filter(~Inquiry.stage.in_(closed_stages))
        .order_by(Inquiry.created_at.desc())
        .first()
    )
    if inquiry:
        return inquiry

    try:
        src = InquirySource(source)
    except ValueError:
        src = InquirySource.PHONE

    is_collab = is_collab_message(message_text)
    # WhatsApp's channel identity is itself a phone number -- a phone is
    # always "given" there. Instagram has no inherent phone signal, so it's
    # only true when the message text itself contains one.
    has_phone = True if source == InquirySource.WA_DIRECT.value else text_contains_phone(message_text)

    stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=is_collab, has_phone=has_phone)

    inquiry = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest_id,
        stage=InquiryStage.NEW,
        stage_id=stage_id or _stage_id_for(db, tenant_id, InquiryStage.NEW),
        source=src,
    )
    db.add(inquiry)
    db.flush()
    log.info(
        "inquiry_auto_created_from_chat", inquiry_id=inquiry.id, guest_id=guest_id,
        tenant_id=tenant_id, source=source, is_collab=is_collab, has_phone=has_phone,
        stage_id=inquiry.stage_id,
    )
    return inquiry


def get_or_create_from_call(
    db: Session, tenant_id: str, guest_id: str, *, direction: str, answered: bool,
) -> Inquiry:
    """
    Leads360 call auto-create -- unifies calls with the WhatsApp/Instagram
    chat auto-create flow (get_or_create_from_chat). Routed via
    lead_auto_create.resolve_call_entry_stage_id() using the answered/
    unanswered signal already available at call-ingest time (before
    transcription/AI analysis ever runs). See app/workers/tasks/call_ingest.py.
    """
    from app.services.lead_auto_create import resolve_call_entry_stage_id

    closed_stages = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
    inquiry = (
        db.query(Inquiry)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .filter(~Inquiry.stage.in_(closed_stages))
        .order_by(Inquiry.created_at.desc())
        .first()
    )
    if inquiry:
        return inquiry

    src = InquirySource.INBOUND_CALL if direction == "inbound" else InquirySource.OUTBOUND_CALL
    stage_id = resolve_call_entry_stage_id(db, tenant_id, answered=answered)

    inquiry = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest_id,
        stage=InquiryStage.NEW,
        stage_id=stage_id or _stage_id_for(db, tenant_id, InquiryStage.NEW),
        source=src,
    )
    db.add(inquiry)
    db.flush()
    log.info(
        "inquiry_auto_created_from_call", inquiry_id=inquiry.id, guest_id=guest_id,
        tenant_id=tenant_id, direction=direction, answered=answered, stage_id=inquiry.stage_id,
    )
    return inquiry


def update_stage(
    db: Session,
    *,
    tenant_id: str,
    inquiry_id: str,
    new_stage: InquiryStage,
    actor_user_id: str,
    actor_role: str,
    reason: Optional[str] = None,
) -> Inquiry:
    """
    Transition an inquiry to a new stage, enforcing the state machine.

    Forward transitions are always allowed.
    Exit transitions (→ LOST / GHOSTED) are allowed from any non-terminal stage.
    Backward transitions require:
      - actor_role in {owner, manager}
      - reason string supplied
      - an AuditEvent row written

    Raises:
        ValueError:              Inquiry not found.
        InvalidStageTransition:  Disallowed move; API layer converts to 422.
    """
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        raise ValueError(f"Inquiry {inquiry_id} not found")

    current = inquiry.stage

    # No-op: already in target stage
    if current == new_stage:
        return inquiry

    # ── Terminal stages block all further transitions ──────────────────────────
    if current in EXIT_STAGES:
        raise InvalidStageTransition(
            current.value, new_stage.value,
            f"Inquiry is {current.value} (terminal) and cannot be moved further."
        )

    # ── Exit transitions: LOST / GHOSTED from any active stage ────────────────
    if new_stage in EXIT_STAGES:
        _apply_stage(db, inquiry, new_stage, actor_user_id, reason)
        return inquiry

    # ── Forward transition ─────────────────────────────────────────────────────
    if new_stage in ALLOWED_FORWARD.get(current, set()):
        _apply_stage(db, inquiry, new_stage, actor_user_id, reason)
        return inquiry

    # ── Backward transition — needs elevated role + reason ────────────────────
    if _is_backward(current, new_stage):
        if actor_role not in BACKWARD_ROLES:
            raise InvalidStageTransition(
                current.value, new_stage.value,
                f"Only owner or manager can reverse a stage transition "
                f"(actor role: {actor_role})."
            )
        if not reason or not reason.strip():
            raise InvalidStageTransition(
                current.value, new_stage.value,
                "A reason is required when reversing a stage transition."
            )
        _apply_stage(db, inquiry, new_stage, actor_user_id, reason)
        return inquiry

    # ── Anything else is explicitly disallowed ────────────────────────────────
    raise InvalidStageTransition(
        current.value, new_stage.value,
        f"'{current.value}' → '{new_stage.value}' is not an allowed transition. "
        f"Allowed: {[s.value for s in ALLOWED_FORWARD.get(current, set())]} or any exit stage."
    )


def _apply_stage(
    db: Session,
    inquiry: Inquiry,
    new_stage: InquiryStage,
    actor_user_id: str,
    reason: Optional[str],
) -> None:
    """Write the stage change + audit event + Inquiry360 stage log. Caller must commit."""
    old_stage = inquiry.stage
    now = datetime.now(timezone.utc)
    inquiry.stage = new_stage
    inquiry.stage_id = _stage_id_for(db, inquiry.tenant_id, new_stage)
    inquiry.current_stage_entered_at = now

    # M7: Write to inquiry_stage_log (Inquiry360 — immutable stage history)
    try:
        from app.models.inquiry_360 import InquiryStageLog
        from app.models.base import gen_uuid
        log_entry = InquiryStageLog(
            id=gen_uuid(),
            tenant_id=inquiry.tenant_id,
            inquiry_id=inquiry.id,
            from_stage=old_stage.value if old_stage else None,
            to_stage=new_stage.value,
            changed_by=actor_user_id or "system",
            changed_at=now,
            reason=reason or "",
        )
        db.add(log_entry)
    except Exception as exc:
        log.warning("inquiry_stage_log_write_failed", error=str(exc))

    # Write audit event (best-effort — don't crash the transition if audit fails)
    try:
        from app.core.audit import append_audit
        append_audit(
            db,
            tenant_id=inquiry.tenant_id,
            action="inquiry.stage_changed",
            actor_user_id=actor_user_id,
            target_type="inquiry",
            target_id=inquiry.id,
            payload={
                "from_stage": old_stage.value,
                "to_stage": new_stage.value,
                "reason": reason or "",
            },
        )
    except Exception as exc:
        log.warning("audit_write_failed", error=str(exc))

    log.info(
        "inquiry_stage_changed",
        inquiry_id=inquiry.id,
        from_stage=old_stage.value,
        to_stage=new_stage.value,
        actor=actor_user_id,
    )


def update_stage_by_id(
    db: Session,
    *,
    tenant_id: str,
    inquiry_id: str,
    new_stage_id: str,
    actor_user_id: str,
    actor_role: str,
    reason: Optional[str] = None,
) -> Inquiry:
    """
    stage_id-driven transition (Leads360 restructure Phase 1 §2.2) — the
    tenant-configurable-pipeline replacement for update_stage(). Rules,
    data-driven off pipeline_stages instead of a hardcoded enum:

      - Forward: allowed to any stage with a higher `order`.
      - Exit: any stage with is_closed_won/is_closed_lost is reachable from
        any non-terminal stage.
      - Backward (lower `order`): requires actor_role in {owner, manager}
        plus a reason, same guardrail as the legacy update_stage().
      - Terminal stages (is_closed_won/is_closed_lost) block further moves.

    This is additive alongside update_stage() -- callers on a tenant with
    only the seeded default stages get equivalent behavior either way, but
    only this path supports a tenant's custom-added stages. The legacy
    `inquiries.stage` enum column is left untouched by this path (there is
    no general mapping from an arbitrary custom stage back to a fixed
    7-value enum) -- code still reading `inquiry.stage` will see it frozen
    at its last enum-covered value once a tenant customizes their pipeline.
    Migrating those ~30 call sites off the enum is tracked as follow-up
    tickets in the Leads360 restructure plan.
    """
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        raise ValueError(f"Inquiry {inquiry_id} not found")

    new_stage = db.query(PipelineStage).filter_by(id=new_stage_id, tenant_id=tenant_id).first()
    if not new_stage:
        raise ValueError(f"Pipeline stage {new_stage_id} not found")

    current = (
        db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=tenant_id).first()
        if inquiry.stage_id else None
    )

    if current is None:
        # Data anomaly (should be impossible post-migration-043 backfill) --
        # fail loudly rather than silently guessing a starting stage.
        raise ValueError(f"Inquiry {inquiry_id} has no current pipeline stage assigned")

    if current.id == new_stage.id:
        return inquiry

    if current.is_closed_won or current.is_closed_lost:
        raise InvalidStageTransition(
            current.key, new_stage.key,
            f"Inquiry is in a terminal stage ('{current.label}') and cannot be moved further."
        )

    if new_stage.is_closed_won or new_stage.is_closed_lost:
        _apply_stage_by_id(db, inquiry, current, new_stage, actor_user_id, reason)
        return inquiry

    if new_stage.order > current.order:
        _apply_stage_by_id(db, inquiry, current, new_stage, actor_user_id, reason)
        return inquiry

    if new_stage.order < current.order:
        if actor_role not in BACKWARD_ROLES:
            raise InvalidStageTransition(
                current.key, new_stage.key,
                f"Only owner or manager can reverse a stage transition (actor role: {actor_role})."
            )
        if not reason or not reason.strip():
            raise InvalidStageTransition(
                current.key, new_stage.key,
                "A reason is required when reversing a stage transition."
            )
        _apply_stage_by_id(db, inquiry, current, new_stage, actor_user_id, reason)
        return inquiry

    raise InvalidStageTransition(
        current.key, new_stage.key,
        f"'{current.key}' and '{new_stage.key}' have the same pipeline order — not a valid transition."
    )


def _apply_stage_by_id(
    db: Session,
    inquiry: Inquiry,
    old_stage: PipelineStage,
    new_stage: PipelineStage,
    actor_user_id: str,
    reason: Optional[str],
) -> None:
    """Write the stage change + audit event + Inquiry360 stage log. Caller must commit."""
    now = datetime.now(timezone.utc)
    inquiry.stage_id = new_stage.id
    inquiry.current_stage_entered_at = now

    try:
        from app.models.inquiry_360 import InquiryStageLog
        from app.models.base import gen_uuid
        db.add(InquiryStageLog(
            id=gen_uuid(),
            tenant_id=inquiry.tenant_id,
            inquiry_id=inquiry.id,
            from_stage=old_stage.key,
            to_stage=new_stage.key,
            changed_by=actor_user_id or "system",
            changed_at=now,
            reason=reason or "",
        ))
    except Exception as exc:
        log.warning("inquiry_stage_log_write_failed", error=str(exc))

    try:
        from app.core.audit import append_audit
        append_audit(
            db,
            tenant_id=inquiry.tenant_id,
            action="inquiry.stage_changed",
            actor_user_id=actor_user_id,
            target_type="inquiry",
            target_id=inquiry.id,
            payload={"from_stage": old_stage.key, "to_stage": new_stage.key, "reason": reason or ""},
        )
    except Exception as exc:
        log.warning("audit_write_failed", error=str(exc))

    log.info(
        "inquiry_stage_changed", inquiry_id=inquiry.id,
        from_stage=old_stage.key, to_stage=new_stage.key, actor=actor_user_id,
    )


def update_status(db: Session, tenant_id: str, inquiry_id: str, stage: str, **kwargs) -> Inquiry:
    """
    Legacy wrapper — skips state-machine validation.
    Used only by internal workers that make trusted transitions (e.g. call ingest).
    Direct API calls must use update_stage() instead.
    """
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        raise ValueError(f"Inquiry {inquiry_id} not found")
    try:
        new_stage = InquiryStage(stage)
    except ValueError:
        raise ValueError(f"Invalid stage: {stage}")
    inquiry.stage = new_stage
    inquiry.stage_id = _stage_id_for(db, tenant_id, new_stage)
    for k, v in kwargs.items():
        if hasattr(inquiry, k) and v is not None:
            setattr(inquiry, k, v)
    return inquiry


def set_lost_reason(db: Session, tenant_id: str, inquiry_id: str, reason: str, note: Optional[str] = None) -> Inquiry:
    inquiry = update_status(db, tenant_id, inquiry_id, "lost", lost_reason=reason, lost_note=note)
    return inquiry
