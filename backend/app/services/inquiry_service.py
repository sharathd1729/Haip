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
    InquiryStage.LOST: "lost",
    InquiryStage.GHOSTED: "lost",
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
