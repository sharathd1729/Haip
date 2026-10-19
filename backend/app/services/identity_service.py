"""
Identity Service — Public facade for progressive identity resolution.

Delegates engine work to identity_resolution.py.
Provides the clean public API used by Leads360 endpoints and webhooks.

Public API:
  add_signal(db, tenant_id, guest_id, signal_type, value, source, actor_user_id)
      → confidence: float
      Adds a new identity signal to an existing guest.
      Auto-writes DPDP Consent row for phone/email signals added by an agent.

  resolve_gid(db, tenant_id, signal_type, value, source, guest_fields)
      → (guest_id: str, created: bool)
      Resolves or creates a guest from an inbound identity signal.

  merge_guests(db, tenant_id, survivor_id, deprecated_id)
      → None
      Merges deprecated guest into survivor. Idempotent.

  get_confidence_score(db, tenant_id, guest_id)
      → float
      Returns the highest confidence score across all signals for a guest.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
import structlog

from app.models.guest_identity import GuestIdentity
from app.services import identity_resolution

log = structlog.get_logger()

_now = lambda: datetime.now(timezone.utc)

# Signal types that require DPDP consent when manually added by an agent
_PII_SIGNAL_TYPES = {"phone", "whatsapp_number", "email"}


def _phone_token(value: str) -> str:
    """Hash a phone/email for safe log correlation. Never log raw PII."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def add_signal(
    db: Session,
    tenant_id: str,
    guest_id: str,
    signal_type: str,
    value: str,
    source: str = "system",
    actor_user_id: Optional[str] = None,
    observed_at: Optional[datetime] = None,
) -> float:
    """
    Add a new identity signal to an existing guest.
    ``observed_at`` = when the guest actually gave it (a backfill of an old message); default now.

    Steps:
      1. Delegate to identity_resolution.enrich_guest() for signal storage + merge detection
      2. If signal_type is phone/email AND actor_user_id provided: write DPDP Consent row
      3. Log with hashed value — never raw PII in logs

    Returns:
      confidence (float) — 0.0–1.0 for this signal
    """
    # Validate guest belongs to this tenant
    from app.models.guest import Guest
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id, is_deleted=False).first()
    if not guest:
        raise ValueError(f"Guest {guest_id!r} not found in tenant {tenant_id!r}")

    confidence = identity_resolution.enrich_guest(
        db=db,
        tenant_id=tenant_id,
        guest_id=guest_id,
        identity_type=signal_type,
        identity_value=value,
        source=source,
        observed_at=observed_at,
    )

    # DPDP: auto-write consent for PII signals added by a human agent
    if signal_type in _PII_SIGNAL_TYPES and actor_user_id:
        _write_consent(db, tenant_id=tenant_id, guest_id=guest_id,
                       signal_type=signal_type, actor_user_id=actor_user_id)

    log.info(
        "identity_signal_added",
        tenant_id=tenant_id,
        guest_id=guest_id,
        signal_type=signal_type,
        value_token=_phone_token(value) if signal_type in _PII_SIGNAL_TYPES else value[:8],
        confidence=confidence,
        source=source,
        actor=actor_user_id or "system",
    )
    return confidence


def resolve_gid(
    db: Session,
    tenant_id: str,
    signal_type: str,
    value: str,
    source: str = "system",
    guest_fields: Optional[dict] = None,
) -> tuple[str, bool]:
    """
    Resolve an inbound signal to a canonical GID.

    Returns (guest_id, created) — created=True if a new guest was made.
    Delegates entirely to identity_resolution.resolve_or_create().
    """
    return identity_resolution.resolve_or_create(
        db=db,
        tenant_id=tenant_id,
        identity_type=signal_type,
        identity_value=value,
        source=source,
        guest_fields=guest_fields or {},
    )


def find_person_by_phone(db: Session, tenant_id: str, phone: str) -> Optional[str]:
    """The guest who already has this number, or None. Read-only. Exact normalised (E.164) match on a phone or WhatsApp
    signal first, then on a guest's own phone column -- a mirrored personal-WhatsApp chat or an Instagram guest whose number
    was saved without a signal is the same person, never a new one."""
    from app.models.guest import Guest
    from app.services import phone_identity

    region = phone_identity.region_for_tenant(db, tenant_id)
    e164 = phone_identity.normalize(phone, region)
    if not e164:
        return None
    for kind in ("phone", "whatsapp_number"):
        sig = identity_resolution._lookup_signal(db, tenant_id, kind, e164)
        if sig is not None:
            guest = db.query(Guest.id).filter_by(id=sig.guest_id, tenant_id=tenant_id, is_deleted=False).first()
            if guest is not None:
                return sig.guest_id
    tail = "".join(ch for ch in e164 if ch.isdigit())[-8:]
    rows = (db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.is_deleted.is_(False), Guest.phone.like(f"%{tail}"))
            .order_by(Guest.created_at.asc()).limit(20).all())
    for g in rows:
        if phone_identity.normalize(g.phone, region) == e164:
            return g.id
    return None


def resolve_person_by_phone(
    db: Session,
    tenant_id: str,
    phone: str,
    *,
    name: Optional[str] = None,
    source: str = "agent_manual",
    actor_user_id: Optional[str] = None,
) -> tuple[str, bool]:
    """(guest_id, created) for a number an agent typed in. Reuses the person find_person_by_phone() finds (attaching the
    phone signal when they only had the number on the guest row, which also makes them a counted lead), else creates one.
    DPDP consent is written for the agent-added number either way. Raises ValueError for an unusable number."""
    from app.services import phone_identity

    e164 = phone_identity.normalize(phone, phone_identity.region_for_tenant(db, tenant_id))
    if not e164:
        raise ValueError("That is not a usable phone number.")
    existing = find_person_by_phone(db, tenant_id, e164)
    if existing:
        has_signal = any(identity_resolution._lookup_signal(db, tenant_id, k, e164) for k in ("phone", "whatsapp_number"))
        if not has_signal:
            add_signal(db, tenant_id, existing, "phone", e164, source=source, actor_user_id=actor_user_id)
        return existing, False
    guest_id, created = resolve_gid(db, tenant_id, "phone", e164, source=source, guest_fields={"name": name} if name else {})
    if created and actor_user_id:
        _write_consent(db, tenant_id=tenant_id, guest_id=guest_id, signal_type="phone", actor_user_id=actor_user_id)
    return guest_id, created


def merge_guests(
    db: Session,
    tenant_id: str,
    survivor_id: str,
    deprecated_id: str,
    *,
    actor_user_id: Optional[str] = None,
    reason: str = "exact_identity_match",
) -> None:
    """
    Merge deprecated guest into survivor. Idempotent — safe to call twice.
    ``reason`` is "manual" for a merge a person approved; every merge is logged and can be undone (guest_merge_events).

    After merge:
      - All identity signals re-pointed to survivor
      - All inquiries/calls/conversations re-linked to survivor
      - deprecated guest is soft-deleted (deletion_state="merged")
      - A system stage_log entry is written to all survivor's inquiries
    """
    if survivor_id == deprecated_id:
        return

    identity_resolution.merge_guests(
        db=db,
        tenant_id=tenant_id,
        survivor_id=survivor_id,
        deprecated_id=deprecated_id,
        actor_user_id=actor_user_id,
        reason=reason,
    )

    # Write system timeline event to inquiry_stage_log for all survivor's inquiries
    _write_merge_stage_event(db, tenant_id=tenant_id, survivor_id=survivor_id,
                              deprecated_id=deprecated_id)

    log.info("identity_merge_completed",
             survivor=survivor_id, deprecated=deprecated_id, tenant_id=tenant_id)


def get_confidence_score(
    db: Session,
    tenant_id: str,
    guest_id: str,
) -> float:
    """
    Return the maximum confidence score across all identity signals for a guest.
    Returns 0.0 if no signals found.
    """
    signals = (
        db.query(GuestIdentity)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .all()
    )
    if not signals:
        return 0.0
    return max(s.confidence for s in signals)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _write_consent(
    db: Session,
    tenant_id: str,
    guest_id: str,
    signal_type: str,
    actor_user_id: str,
) -> None:
    """Write DPDP consent row for agent-manually-added PII signal."""
    try:
        from app.models.consent import Consent
        from app.models.base import gen_uuid

        now_iso = _now().isoformat()
        consent = Consent(
            id=gen_uuid(),
            tenant_id=tenant_id,
            guest_id=guest_id,
            channel="crm",
            scope="profiling",
            granted=True,
            source="agent_manual",
            recorded_at=now_iso,
            proof_source="/leads",
            consent_payload={"signal_type": signal_type, "collected_by": actor_user_id},
        )
        db.add(consent)
        db.flush()
        log.info("dpdp_consent_written", tenant_id=tenant_id, guest_id=guest_id,
                 signal_type=signal_type, actor=actor_user_id)
    except Exception as exc:
        # Consent write must not block the signal addition
        log.warning("dpdp_consent_write_failed", error=str(exc),
                    tenant_id=tenant_id, guest_id=guest_id)


def _write_merge_stage_event(
    db: Session,
    tenant_id: str,
    survivor_id: str,
    deprecated_id: str,
) -> None:
    """
    Write a system entry to inquiry_stage_log for all of the survivor's
    active inquiries so the timeline shows a merge event.
    """
    try:
        from app.models.inquiry import Inquiry
        from app.models.inquiry_360 import InquiryStageLog
        from app.models.base import gen_uuid

        inquiries = (
            db.query(Inquiry)
            .filter_by(tenant_id=tenant_id, guest_id=survivor_id)
            .all()
        )
        now = _now()
        for inq in inquiries:
            entry = InquiryStageLog(
                id=gen_uuid(),
                tenant_id=tenant_id,
                inquiry_id=inq.id,
                from_stage=None,
                to_stage="merged",
                changed_by="system",
                changed_at=now,
                reason=f"Lead merged with deprecated guest {deprecated_id[:8]}",
            )
            db.add(entry)

            # Mirror the merge onto the guest_events ledger (Guest Journey).
            try:
                from app.core.events import emit_event
                from app.schemas.guest_events import GuestEventType, SourceModule

                emit_event(
                    db,
                    tenant_id=tenant_id,
                    event_type=GuestEventType.INQUIRY_MERGED,
                    entity_type="inquiry",
                    entity_id=entry.id,
                    source_module=SourceModule.LEADS360,
                    occurred_at=now,
                    guest_id=survivor_id,
                    inquiry_id=inq.id,
                    channel="system",
                    direction="system",
                    preview=entry.reason[:120],
                    payload={"deprecated_guest_id": deprecated_id},
                )
            except Exception as exc:
                log.warning("guest_event_merge_write_failed", error=str(exc))

        # The deprecated GID's history must follow it onto the survivor, or the
        # merged guest's journey silently loses everything from before the merge.
        try:
            from app.services import guest_events_service

            guest_events_service.attach_guest(
                db, tenant_id, from_guest_id=deprecated_id, to_guest_id=survivor_id
            )
        except Exception as exc:
            log.warning("guest_event_reattach_failed", error=str(exc))
    except Exception as exc:
        log.warning("merge_stage_event_write_failed", error=str(exc))
