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


# Legacy enum member -> the meaning-flag on the tenant's own pipeline_stages (used when the legacy key is gone).
_ENUM_TO_STAGE_FLAG: dict[InquiryStage, str] = {
    InquiryStage.NEW: "is_valid_lead_entry",
    InquiryStage.RESPONDING: "is_valid_lead_entry",
    InquiryStage.QUOTED: "is_valid_lead_entry",
    InquiryStage.SITE_VISIT: "is_valid_lead_entry",
    InquiryStage.SITE_VISIT_SCHEDULED: "is_valid_lead_entry",
    InquiryStage.SITE_VISIT_DONE: "is_valid_lead_entry",
    InquiryStage.BOOKED: "is_closed_won",
    InquiryStage.LOST: "is_closed_lost",
    InquiryStage.GHOSTED: "is_closed_lost",
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
        if row:
            return row[0]
        # The taxonomy was replaced wholesale (migration 049: active / unsuitable / lost / sold ...), so the legacy keys above
        # no longer exist for a migrated tenant. Resolve by what the stage MEANS (the flags the tenant owns) instead of
        # returning None, which left the inquiry off the board and out of every stage count.
        flag = _ENUM_TO_STAGE_FLAG.get(stage)
        if flag is None:
            return None
        row = (
            db.query(PipelineStage.id)
            .filter(PipelineStage.tenant_id == tenant_id, getattr(PipelineStage, flag).is_(True))
            .order_by(PipelineStage.order)
            .first()
        )
        if row is None and flag == "is_valid_lead_entry":
            row = db.query(PipelineStage.id).filter_by(tenant_id=tenant_id, is_default_entry=True).first()
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
        from app.services.lead_assignment_service import assign_new_lead
        assign_new_lead(db, inquiry)
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
    # always "given" there, on both the organic (WA_DIRECT) and ad-attributed
    # (CLICK_TO_WA) paths. Instagram has no inherent phone signal, so it's
    # only true when the message text itself contains one.
    has_phone = (
        True if source in (InquirySource.WA_DIRECT.value, InquirySource.CLICK_TO_WA.value)
        else text_contains_phone(message_text)
    )

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
    from app.services.lead_assignment_service import assign_new_lead
    assign_new_lead(db, inquiry)
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

    # An inbound call that starts a lead is an organic call: nothing in the call itself says an ad or a campaign sent it, and
    # a click-to-call from an ad would arrive through the attributed channel instead. Older call leads keep their source.
    src = InquirySource.ORGANIC_CALL if direction == "inbound" else InquirySource.OUTBOUND_CALL
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


def create_manual_lead(
    db: Session, tenant_id: str, actor_user_id: str, *,
    guest_name: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    source: str = "walk_in",
    property_id: Optional[str] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    adults: Optional[int] = None,
    children: Optional[int] = None,
    occasion: Optional[str] = None,
    budget: Optional[float] = None,
    assigned_to: Optional[str] = None,
) -> Inquiry:
    """
    Leads360 manual lead entry -- an agent typing a guest's details straight
    into the pipeline, no inbound message/call to auto-create from. Routed
    through the same identity_service GID resolution and lead_auto_create
    entry-stage logic every other creation path uses (CLAUDE.md: identity_
    service is the only place for GID ops), so a manually-added lead who
    later messages/calls in resolves to the same guest instead of a
    duplicate, and lands in the tenant's real "valid lead" stage rather
    than a hardcoded key that may not exist for this tenant's taxonomy.
    """
    from app.services import identity_service

    if not phone and not email:
        raise ValueError("Provide at least a phone number or email to add a lead.")

    primary_type = "phone" if phone else "email"
    primary_value = phone or email
    guest_id, created = identity_service.resolve_gid(
        db, tenant_id, signal_type=primary_type, value=primary_value,
        source="agent_manual", guest_fields={"name": guest_name},
    )
    if created:
        # resolve_gid's own guest-creation path (_create_guest) doesn't
        # write DPDP consent -- only identity_service.add_signal() does
        # (CLAUDE.md SECURITY: "Agent-added phone/email signals: auto-write
        # Consent row"). Reusing that same private helper here rather than
        # duplicating the consent-writing logic.
        identity_service._write_consent(
            db, tenant_id=tenant_id, guest_id=guest_id,
            signal_type=primary_type, actor_user_id=actor_user_id,
        )
    if phone and email:
        # Second signal on the same guest -- add_signal's own consent path
        # covers this one directly.
        identity_service.add_signal(
            db, tenant_id=tenant_id, guest_id=guest_id,
            signal_type="email", value=email, source="agent_manual",
            actor_user_id=actor_user_id,
        )

    try:
        src = InquirySource(source)
    except ValueError:
        src = InquirySource.WALK_IN

    inquiry = create_lead_for_guest(
        db, tenant_id, guest_id, source=src, has_phone=bool(phone), property_id=property_id, check_in=check_in,
        check_out=check_out, adults=adults, children=children, occasion=occasion, budget=budget, assigned_to=assigned_to,
    )
    log.info(
        "lead_manually_created", inquiry_id=inquiry.id, guest_id=guest_id,
        tenant_id=tenant_id, actor_user_id=actor_user_id, stage_id=inquiry.stage_id,
    )
    return inquiry


def create_lead_for_guest(
    db: Session, tenant_id: str, guest_id: str, *,
    source: Optional[InquirySource],
    has_phone: bool,
    property_id: Optional[str] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    adults: Optional[int] = None,
    children: Optional[int] = None,
    occasion: Optional[str] = None,
    budget: Optional[float] = None,
    assigned_to: Optional[str] = None,
    commit: bool = True,
) -> Inquiry:
    """A new lead (inquiry) for a person already resolved by identity_service, landing in the tenant's entry stage
    (lead_auto_create rules) and assigned like every other new lead. Used by create_manual_lead and by the rate calculator
    when a returning guest (all earlier leads Sold or Lost) asks for a new trip. ``source=None`` = not recorded."""
    from app.services.lead_auto_create import resolve_entry_stage_id

    stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=False, has_phone=has_phone)
    inquiry = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest_id,
        property_id=property_id,
        stage=InquiryStage.NEW,
        stage_id=stage_id or _stage_id_for(db, tenant_id, InquiryStage.NEW),
        source=source,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        children=children,
        occasion=occasion,
        budget=budget,
        assigned_to=assigned_to,
        assigned_at=datetime.now(timezone.utc) if assigned_to else None,
        assignment_method="manual" if assigned_to else None,
    )
    db.add(inquiry)
    db.flush()
    if not assigned_to:
        from app.services.lead_assignment_service import assign_new_lead
        assign_new_lead(db, inquiry)
    if commit:
        db.commit()
        db.refresh(inquiry)
    else:
        db.flush()
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


def _notify_stage_hooks(db: Session, inquiry: Inquiry, actor_user_id: Optional[str]) -> None:
    """Called by BOTH transition paths (_apply_stage and _apply_stage_by_id), like _emit_stage_ledger_event: a hook on
    only one would miss every move made through the other. Today: the lead autopilot closes its open decisions when a
    person moves the lead (lead_autopilot_service.on_stage_changed). Best-effort -- never blocks the transition."""
    try:
        from app.services import lead_autopilot_service
        lead_autopilot_service.on_stage_changed(db, inquiry, inquiry.stage_id, actor_user_id)
    except Exception as exc:
        log.warning("lead_autopilot_stage_hook_failed", inquiry_id=inquiry.id, error=str(exc)[:200])


def revert_automatic_move(
    db: Session,
    *,
    tenant_id: str,
    inquiry_id: str,
    expected_stage_id: str,
    restore_stage_id: str,
    actor_user_id: str,
    reason: str,
) -> Inquiry:
    """Undo ONE lead-autopilot move: put the lead back in the stage it was in before.

    Narrower than update_stage_by_id/reopen_lost_inquiry on purpose: it only works while the lead is still in the stage
    the autopilot put it in (expected_stage_id -- otherwise a person has moved it since and their move wins), never out
    of a Sold stage (that is a booking: cancel the booking instead), and only back into an open stage. Writes the same
    stage log, ledger event and audit row as any move. Clears the lost reason when leaving Lost (the caller restores
    the previous one). Caller commits."""
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        raise ValueError(f"Inquiry {inquiry_id} not found")
    current = db.query(PipelineStage).filter_by(id=expected_stage_id, tenant_id=tenant_id).first()
    target = db.query(PipelineStage).filter_by(id=restore_stage_id, tenant_id=tenant_id).first()
    if current is None or target is None:
        raise ValueError("Pipeline stage not found")
    if inquiry.stage_id != current.id:
        raise InvalidStageTransition(current.key, target.key, "The lead has been moved since; this change can't be undone.")
    if current.is_closed_won:
        raise InvalidStageTransition(current.key, target.key, "A Sold lead is a booking. Cancel the booking instead.")
    if target.is_closed_won or target.is_closed_lost:
        raise InvalidStageTransition(current.key, target.key, "An undo can only return the lead to an open stage.")
    _apply_stage_by_id(db, inquiry, current, target, actor_user_id, reason)
    if current.is_closed_lost:
        inquiry.lost_reason = None
        inquiry.lost_note = None
    return inquiry


def _emit_stage_ledger_event(
    db: Session,
    inquiry: Inquiry,
    *,
    stage_log_id: Optional[str],
    from_key: Optional[str],
    to_key: str,
    actor_user_id: Optional[str],
    reason: Optional[str],
    occurred_at: datetime,
) -> None:
    """
    Mirror a stage transition into the guest_events ledger (Guest Journey).

    Shared by both transition paths — the legacy enum one (_apply_stage) and the
    stage_id one (_apply_stage_by_id). Keep it that way: a hook added to only one
    silently misses every transition that goes through the other.

    Best-effort, matching the stage-log and audit writes either side of it — a
    ledger problem must never block the transition itself.
    """
    if not stage_log_id:
        return
    try:
        from app.core.events import emit_event
        from app.schemas.guest_events import GuestEventType, SourceModule

        emit_event(
            db,
            tenant_id=inquiry.tenant_id,
            event_type=GuestEventType.INQUIRY_STAGE_MOVED,
            entity_type="inquiry",
            entity_id=stage_log_id,
            source_module=SourceModule.LEADS360,
            occurred_at=occurred_at,
            guest_id=inquiry.guest_id,
            inquiry_id=inquiry.id,
            channel="system",
            direction="system",
            preview=(reason or f"Stage → {to_key}")[:120],
            actor_user_id=actor_user_id or None,
            payload={"from_stage": from_key, "to_stage": to_key},
        )
    except Exception as exc:
        log.warning("guest_event_stage_write_failed", error=str(exc))


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
        _stage_log_id = log_entry.id
    except Exception as exc:
        _stage_log_id = None
        log.warning("inquiry_stage_log_write_failed", error=str(exc))

    _emit_stage_ledger_event(
        db, inquiry,
        stage_log_id=_stage_log_id,
        from_key=old_stage.value if old_stage else None,
        to_key=new_stage.value,
        actor_user_id=actor_user_id,
        reason=reason,
        occurred_at=now,
    )

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

    _notify_stage_hooks(db, inquiry, actor_user_id)

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


def reopen_lost_inquiry(
    db: Session,
    *,
    tenant_id: str,
    inquiry_id: str,
    new_stage_id: str,
    actor_user_id: Optional[str],
    actor_role: str,
    reason: str,
) -> Inquiry:
    """Bring a lead back from Lost into an open stage.

    update_stage_by_id() deliberately treats Lost as terminal, so it can't do this. Reopening is a
    separate, narrower action: owner/manager (or a trusted script, role "system") only, a reason is
    mandatory, only a LOST lead can be reopened (a Sold lead is a booking and stays sold), and the
    target must be an open stage. It writes the same stage log, ledger event and audit entry as any
    other move, and clears the lost reason/note so reports don't count it as lost.
    """
    if actor_role not in BACKWARD_ROLES and actor_role != "system":
        raise InvalidStageTransition("lost", "open", "Only an owner or manager can reopen a lost lead.")
    if not reason or not reason.strip():
        raise InvalidStageTransition("lost", "open", "A reason is required to reopen a lost lead.")

    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        raise ValueError(f"Inquiry {inquiry_id} not found")
    current = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=tenant_id).first() if inquiry.stage_id else None
    target = db.query(PipelineStage).filter_by(id=new_stage_id, tenant_id=tenant_id).first()
    if not target:
        raise ValueError(f"Pipeline stage {new_stage_id} not found")
    if current is None or not current.is_closed_lost:
        raise InvalidStageTransition(
            current.key if current else "none", target.key, "Only a lead in a Lost stage can be reopened.")
    if target.is_closed_lost or target.is_closed_won:
        raise InvalidStageTransition(current.key, target.key, "Choose an open stage to reopen the lead into.")

    _apply_stage_by_id(db, inquiry, current, target, actor_user_id, reason)
    inquiry.lost_reason = None
    inquiry.lost_note = None
    return inquiry


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
    # Keep the legacy enum in step: code that still reads it (open-inquiry lookups, closed filters) must not see a Lost or
    # Sold lead as open, nor a re-opened one as closed.
    if new_stage.is_closed_won:
        inquiry.stage = InquiryStage.BOOKED
    elif new_stage.is_closed_lost:
        inquiry.stage = InquiryStage.LOST
    elif inquiry.stage in (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED):
        inquiry.stage = InquiryStage.RESPONDING if new_stage.category == "valid" else InquiryStage.NEW

    try:
        from app.models.inquiry_360 import InquiryStageLog
        from app.models.base import gen_uuid
        _stage_log = InquiryStageLog(
            id=gen_uuid(),
            tenant_id=inquiry.tenant_id,
            inquiry_id=inquiry.id,
            from_stage=old_stage.key,
            to_stage=new_stage.key,
            changed_by=actor_user_id or "system",
            changed_at=now,
            reason=reason or "",
        )
        db.add(_stage_log)
        _stage_log_id = _stage_log.id
    except Exception as exc:
        _stage_log_id = None
        log.warning("inquiry_stage_log_write_failed", error=str(exc))

    _emit_stage_ledger_event(
        db, inquiry,
        stage_log_id=_stage_log_id,
        from_key=old_stage.key,
        to_key=new_stage.key,
        actor_user_id=actor_user_id,
        reason=reason,
        occurred_at=now,
    )

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

    _notify_stage_hooks(db, inquiry, actor_user_id)

    log.info(
        "inquiry_stage_changed", inquiry_id=inquiry.id,
        from_stage=old_stage.key, to_stage=new_stage.key, actor=actor_user_id,
    )

    if new_stage.is_closed_won:
        _create_stay_for_won_inquiry(db, inquiry)


def _create_stay_for_won_inquiry(db: Session, inquiry: Inquiry) -> None:
    """
    A lead marked as won ("Sold") represents a real booking -- create the
    Stay record so it shows up alongside PMS-synced bookings on the
    property calendar. HAIP is not the source of truth for bookings
    (Hostaway/eZee are, per CLAUDE.md), but a directly-sold lead has no
    PMS counterpart to sync from, so this is the only way it ever becomes
    a Stay. hostaway_booking_id is left null (not PMS-sourced);
    channel_source="direct" distinguishes it from PMS-synced rows.

    property_id/check_in/check_out are required on Stay (NOT NULL) but are
    often unset on chat/WhatsApp-sourced leads -- skip (log, don't block
    the stage move) rather than writing a half-populated Stay.
    """
    if not (inquiry.property_id and inquiry.check_in and inquiry.check_out):
        log.warning(
            "won_inquiry_missing_booking_fields_no_stay_created",
            inquiry_id=inquiry.id,
            has_property_id=bool(inquiry.property_id),
            has_check_in=bool(inquiry.check_in),
            has_check_out=bool(inquiry.check_out),
        )
        return

    # migration 071: Stay.check_in/check_out are real DATE columns;
    # Inquiry.check_in/check_out are untouched (still ISO strings) -- parse
    # before constructing Stay. Same "skip, log, don't block the stage
    # move" treatment as the missing-field case above for a malformed one.
    from datetime import date as _date
    try:
        stay_check_in = _date.fromisoformat(inquiry.check_in)
        stay_check_out = _date.fromisoformat(inquiry.check_out)
    except ValueError:
        log.warning(
            "won_inquiry_unparseable_dates_no_stay_created",
            inquiry_id=inquiry.id, check_in=inquiry.check_in, check_out=inquiry.check_out,
        )
        return

    from app.models.property import Stay
    from app.models.base import gen_uuid

    existing = db.query(Stay).filter_by(inquiry_id=inquiry.id).first()
    if existing:
        return  # idempotent -- a re-entry into the won stage shouldn't duplicate the Stay

    amount = inquiry.quoted_amount if inquiry.quoted_amount is not None else inquiry.budget
    stay = Stay(
        id=gen_uuid(),
        tenant_id=inquiry.tenant_id,
        guest_id=inquiry.guest_id,
        property_id=inquiry.property_id,
        inquiry_id=inquiry.id,
        check_in=stay_check_in,
        check_out=stay_check_out,
        adults=inquiry.adults or 1,
        children=inquiry.children or 0,
        status="confirmed",
        total_amount=amount,
        currency=inquiry.currency or "INR",
        occasion=inquiry.occasion,
        channel_source="direct",
    )
    db.add(stay)
    db.flush(objects=[stay])
    log.info("stay_created_from_won_inquiry", inquiry_id=inquiry.id, stay_id=stay.id)


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
