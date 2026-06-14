"""
Identity Resolution Engine — Progressive guest identity matching.

Replaces phone-as-primary-key dedup with a multi-signal identity graph.

Public API:
  resolve_or_create(db, tenant_id, signal_type, signal_value, source, **guest_fields)
      → (guest_id: str, created: bool)

  enrich_guest(db, tenant_id, guest_id, signal_type, signal_value, source)
      → confidence: float

  merge_guests(db, tenant_id, survivor_id, deprecated_id)
      → None  (emits guest.merged event stub)

Matching stages:
  1. Deterministic — exact (tenant_id, type, value) lookup
  2. Probabilistic  — composite score across known signals
  3. New guest      — when score < REVIEW_THRESHOLD
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.guest_identity import (
    GuestIdentity,
    IdentityType,
    SIGNAL_CONFIDENCE,
    MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
)
from app.models.base import gen_uuid

log = logging.getLogger(__name__)

_now = lambda: datetime.now(timezone.utc)


# ─── Normalisers ─────────────────────────────────────────────────────────────

def _normalise(identity_type: str, value: str) -> str:
    """Return a canonical form of the identity value."""
    v = value.strip()
    if identity_type in (IdentityType.PHONE, IdentityType.WHATSAPP_NUMBER):
        # Strip WhatsApp suffix, then ensure E.164 with leading +
        v = re.sub(r"@s\.whatsapp\.net$", "", v)
        v = re.sub(r"[^\d+]", "", v)
        if v and not v.startswith("+"):
            # Assume Indian number if 10 digits
            v = "+91" + v if len(v) == 10 else "+" + v
    elif identity_type == IdentityType.EMAIL:
        v = v.lower()
    elif identity_type == IdentityType.CHANNEL_THREAD_ID:
        # Must be namespaced: "airbnb:AB-123"
        v = v.lower()
    return v


# ─── Core lookup ─────────────────────────────────────────────────────────────

def _lookup_signal(
    db: Session,
    tenant_id: str,
    identity_type: str,
    identity_value: str,
) -> Optional[GuestIdentity]:
    """Exact match on (tenant_id, type, value)."""
    return (
        db.query(GuestIdentity)
        .filter_by(
            tenant_id=tenant_id,
            identity_type=identity_type,
            identity_value=identity_value,
        )
        .first()
    )


def _signals_for_guest(db: Session, tenant_id: str, guest_id: str) -> list[GuestIdentity]:
    return (
        db.query(GuestIdentity)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .all()
    )


# ─── Probabilistic match ─────────────────────────────────────────────────────

def _find_best_candidate(
    db: Session,
    tenant_id: str,
    identity_type: str,
    identity_value: str,
) -> tuple[Optional[str], float]:
    """
    Look for an existing guest that might own this signal via cross-signal
    overlap. Returns (guest_id, composite_score) or (None, 0.0).

    Strategy: if a PHONE / WHATSAPP_NUMBER match failed on type but the value
    looks like a phone, try the other phone-class types.
    """
    phone_types = {IdentityType.PHONE, IdentityType.WHATSAPP_NUMBER}

    if identity_type in phone_types:
        # Try the other phone class
        alt_type = (
            IdentityType.PHONE
            if identity_type == IdentityType.WHATSAPP_NUMBER
            else IdentityType.WHATSAPP_NUMBER
        )
        match = _lookup_signal(db, tenant_id, alt_type, identity_value)
        if match:
            # Cross-class phone match — high confidence
            return match.guest_id, 0.87

    return None, 0.0


# ─── Public API ──────────────────────────────────────────────────────────────

def resolve_or_create(
    db: Session,
    tenant_id: str,
    identity_type: str,
    identity_value: str,
    source: str = "system",
    guest_fields: Optional[dict] = None,
) -> tuple[str, bool]:
    """
    Resolve an inbound signal to a Guest ID.

    Returns:
        (guest_id, created)   created=True if a new guest was made

    Steps:
      1. Normalise value
      2. Exact signal lookup → found → return GID
      3. Probabilistic match → score ≥ MERGE_THRESHOLD → attach signal, return GID
      4. No match → create guest + signal
    """
    value = _normalise(identity_type, identity_value)
    if not value:
        raise ValueError(f"Empty identity value after normalisation: {identity_value!r}")

    # Stage 1: deterministic
    existing = _lookup_signal(db, tenant_id, identity_type, value)
    if existing:
        _touch_signal(db, existing)
        return existing.guest_id, False

    # Stage 2: probabilistic
    candidate_gid, score = _find_best_candidate(db, tenant_id, identity_type, value)
    if candidate_gid and score >= MERGE_THRESHOLD:
        _attach_signal(db, tenant_id, candidate_gid, identity_type, value, source, score)
        log.info("identity_resolved_probabilistic",
                 tenant_id=tenant_id, type=identity_type, score=score, gid=candidate_gid)
        return candidate_gid, False

    if candidate_gid and score >= REVIEW_THRESHOLD:
        # Flag for human review but still create a new guest (conservative)
        log.warning("identity_merge_flagged",
                    tenant_id=tenant_id, type=identity_type, score=score,
                    candidate_gid=candidate_gid)

    # Stage 3: new guest
    guest_id = _create_guest(db, tenant_id, identity_type, value, source, guest_fields or {})
    return guest_id, True


def enrich_guest(
    db: Session,
    tenant_id: str,
    guest_id: str,
    identity_type: str,
    identity_value: str,
    source: str = "system",
) -> float:
    """
    Add a new identity signal to an already-known guest.
    Returns the new confidence for this signal.

    Also checks whether another guest already owns this signal:
      → If yes: triggers merge (deprecated → survivor = guest_id).
    """
    value = _normalise(identity_type, identity_value)
    if not value:
        return 0.0

    # Check if another guest owns this signal
    conflict = _lookup_signal(db, tenant_id, identity_type, value)
    if conflict and conflict.guest_id != guest_id:
        log.info("identity_enrich_triggers_merge",
                 survivor=guest_id, deprecated=conflict.guest_id,
                 type=identity_type)
        merge_guests(db, tenant_id, survivor_id=guest_id, deprecated_id=conflict.guest_id)
        return conflict.confidence

    if not conflict:
        conf = SIGNAL_CONFIDENCE.get(identity_type, 0.60)
        _attach_signal(db, tenant_id, guest_id, identity_type, value, source, conf)
        log.info("identity_signal_added",
                 tenant_id=tenant_id, guest_id=guest_id, type=identity_type)
        return conf

    # Already on this guest — just touch
    _touch_signal(db, conflict)
    return conflict.confidence


def merge_guests(
    db: Session,
    tenant_id: str,
    survivor_id: str,
    deprecated_id: str,
) -> None:
    """
    Merge deprecated guest into survivor.
    Re-points all identity signals; marks deprecated guest deleted.
    """
    if survivor_id == deprecated_id:
        return

    # Re-point all signals from deprecated to survivor
    signals = _signals_for_guest(db, tenant_id, deprecated_id)
    for sig in signals:
        # Check for duplicate type+value on survivor (skip if collision)
        collision = _lookup_signal(db, tenant_id, sig.identity_type, sig.identity_value)
        if collision and collision.guest_id == survivor_id:
            db.delete(sig)
        else:
            sig.guest_id = survivor_id
            db.add(sig)

    # Re-point related entities
    _repoint_entities(db, tenant_id, deprecated_id, survivor_id)

    # Soft-delete the deprecated guest
    from app.models.guest import Guest
    dep = db.query(Guest).filter_by(id=deprecated_id, tenant_id=tenant_id).first()
    if dep:
        dep.is_deleted = True
        dep.deletion_state = "merged"
        db.add(dep)

    db.commit()
    log.info("guest_merged", survivor=survivor_id, deprecated=deprecated_id, tenant_id=tenant_id)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _create_guest(
    db: Session,
    tenant_id: str,
    identity_type: str,
    identity_value: str,
    source: str,
    fields: dict,
) -> str:
    from app.models.guest import Guest

    # For phone/whatsapp signals, populate phone on the guest row for quick lookup
    phone = None
    if identity_type in (IdentityType.PHONE, IdentityType.WHATSAPP_NUMBER):
        phone = identity_value

    guest = Guest(
        id=gen_uuid(),
        tenant_id=tenant_id,
        phone=phone or "",          # empty string preserves NOT NULL but phone is no longer dedup key
        name=fields.get("name"),
        email=fields.get("email"),
        language_pref=fields.get("language_pref", "en"),
    )
    db.add(guest)
    db.flush()   # get guest.id without committing

    conf = SIGNAL_CONFIDENCE.get(identity_type, 0.60)
    _attach_signal(db, tenant_id, guest.id, identity_type, identity_value, source, conf)
    db.commit()
    log.info("guest_created", tenant_id=tenant_id, guest_id=guest.id,
             source=source, signal_type=identity_type)
    return guest.id


def _attach_signal(
    db: Session,
    tenant_id: str,
    guest_id: str,
    identity_type: str,
    identity_value: str,
    source: str,
    confidence: float,
) -> GuestIdentity:
    now = _now()
    sig = GuestIdentity(
        id=gen_uuid(),
        tenant_id=tenant_id,
        guest_id=guest_id,
        identity_type=identity_type,
        identity_value=identity_value,
        source=source,
        confidence=confidence,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(sig)
    return sig


def _touch_signal(db: Session, signal: GuestIdentity) -> None:
    signal.last_seen_at = _now()
    db.add(signal)


def _repoint_entities(
    db: Session,
    tenant_id: str,
    deprecated_id: str,
    survivor_id: str,
) -> None:
    """
    Re-link core entities from the deprecated guest to the survivor.
    Extend this list as new entity types are added.
    """
    from sqlalchemy import text

    tables = [
        ("inquiries",      "guest_id"),
        ("calls",          "guest_id"),
        ("conversations",  "guest_id"),
        ("stays",          "guest_id"),
    ]
    for table, col in tables:
        try:
            db.execute(
                text(f"UPDATE {table} SET {col} = :sur WHERE {col} = :dep AND tenant_id = :tid"),
                {"sur": survivor_id, "dep": deprecated_id, "tid": tenant_id},
            )
        except Exception as exc:
            log.warning("repoint_entities_skip", table=table, error=str(exc))
