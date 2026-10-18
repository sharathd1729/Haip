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

Lead state. A guest becomes a LEAD (``Guest.lead_identified_at``) the first time a usable phone number is attached to them,
by any route (a WhatsApp number, a call, a number typed in a chat, a booking). A contact with only an Instagram id is a
conversation, not a lead. First touch (channel and time) is written when the guest is created and never overwritten. Names and
usernames never merge anyone: only an exact match on a normalised identity value, or an explicit manual merge, does.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services import phone_identity
from app.services.lead_state import channel_for_source
from app.models.guest_identity import (
    GuestIdentity,
    IdentityType,
    SIGNAL_CONFIDENCE,
    MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
)
from app.models.base import gen_uuid
import structlog

log = structlog.get_logger()

_now = lambda: datetime.now(timezone.utc)


# ─── Normalisers ─────────────────────────────────────────────────────────────

_PHONE_TYPES = (IdentityType.PHONE, IdentityType.WHATSAPP_NUMBER)

def _normalise(identity_type: str, value: str, region: Optional[str] = None) -> str:
    """Return a canonical form of the identity value.

    Phone numbers become E.164 when they are valid numbers (phone_identity). A number written without a country code is read
    in the workspace's own country (``region``); India is not assumed for everybody. A value that is not a valid number still
    gets a stored form (the identity graph has always accepted any number-like string) but it will not count as a lead."""
    v = value.strip()
    if identity_type in _PHONE_TYPES:
        good = phone_identity.normalize(v, region)
        if good:
            return good
        v = re.sub(r"@s\.whatsapp\.net$", "", v)
        v = re.sub(r"[^\d+]", "", v)
        if v and not v.startswith("+"):
            # The old rule, kept only for workspaces known to be Indian: a bare 10-digit number is an Indian number.
            v = "+91" + v if (len(v) == 10 and region == "IN") else "+" + v
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
    region = phone_identity.region_for_tenant(db, tenant_id) if identity_type in _PHONE_TYPES else None
    value = _normalise(identity_type, identity_value, region)
    if not value:
        raise ValueError(f"Empty identity value after normalisation: {identity_value!r}")

    # Stage 1: deterministic
    existing = _lookup_signal(db, tenant_id, identity_type, value)
    if existing:
        _touch_signal(db, existing)
        return existing.guest_id, False

    try:
        # Stage 2: probabilistic
        candidate_gid, score = _find_best_candidate(db, tenant_id, identity_type, value)
        if candidate_gid and score >= MERGE_THRESHOLD:
            _attach_signal(db, tenant_id, candidate_gid, identity_type, value, source, score)
            _backfill_guest_phone(db, tenant_id, candidate_gid, identity_type, value)
            db.flush()
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
    except IntegrityError:
        # Two requests met the same new contact at once; the unique (tenant, type, value) index let one win. Use theirs.
        db.rollback()
        winner = _lookup_signal(db, tenant_id, identity_type, value)
        if winner is None:
            raise
        log.info("identity_create_race_resolved", tenant_id=tenant_id, type=identity_type, gid=winner.guest_id)
        return winner.guest_id, False


def enrich_guest(
    db: Session,
    tenant_id: str,
    guest_id: str,
    identity_type: str,
    identity_value: str,
    source: str = "system",
    observed_at: Optional[datetime] = None,
) -> float:
    """
    Add a new identity signal to an already-known guest.
    Returns the new confidence for this signal.

    ``observed_at``: when the signal was really given (a backfill reading an old message). It becomes the signal's
    first_seen_at and, for the guest's first usable phone, the moment they became a lead -- so a backfill does not count
    old leads as new today. Default: now.

    Also checks whether another guest already owns this signal:
      → If yes: triggers merge (deprecated → survivor = guest_id).
    """
    region = phone_identity.region_for_tenant(db, tenant_id) if identity_type in _PHONE_TYPES else None
    value = _normalise(identity_type, identity_value, region)
    if not value:
        return 0.0

    # Check if another guest owns this signal. A phone number is the same number whether it arrived as a phone or as a
    # WhatsApp number, so both kinds are checked: an Instagram contact who shares the number a WhatsApp lead already has
    # is that lead, not a second one.
    conflict = _lookup_signal(db, tenant_id, identity_type, value)
    if conflict is None and identity_type in _PHONE_TYPES:
        other = IdentityType.PHONE if identity_type == IdentityType.WHATSAPP_NUMBER else IdentityType.WHATSAPP_NUMBER
        conflict = _lookup_signal(db, tenant_id, other, value)
    if conflict and conflict.guest_id != guest_id:
        log.info("identity_enrich_triggers_merge",
                 survivor=guest_id, deprecated=conflict.guest_id,
                 type=identity_type)
        merge_guests(db, tenant_id, survivor_id=guest_id, deprecated_id=conflict.guest_id)
        return conflict.confidence

    if not conflict:
        conf = SIGNAL_CONFIDENCE.get(identity_type, 0.60)
        _attach_signal(db, tenant_id, guest_id, identity_type, value, source, conf, observed_at=observed_at)
        _backfill_guest_phone(db, tenant_id, guest_id, identity_type, value)
        log.info("identity_signal_added",
                 tenant_id=tenant_id, guest_id=guest_id, type=identity_type)
        return conf

    # Already on this guest — just touch
    _touch_signal(db, conflict)
    return conflict.confidence


_MOVED_TABLES = ("inquiries", "calls", "conversations", "stays")


def _lead_state(guest) -> dict:
    return {
        "lead_identified_at": guest.lead_identified_at.isoformat() if guest.lead_identified_at else None,
        "lead_identified_via": guest.lead_identified_via,
        "first_touch_channel": guest.first_touch_channel,
        "first_touch_at": guest.first_touch_at.isoformat() if guest.first_touch_at else None,
    }


def merge_guests(
    db: Session,
    tenant_id: str,
    survivor_id: str,
    deprecated_id: str,
    *,
    actor_user_id: Optional[str] = None,
    reason: str = "exact_identity_match",
):
    """
    Merge deprecated guest into survivor.
    Re-points all identity signals and related records; marks deprecated guest deleted (soft: nothing is removed).

    Every merge is written to ``guest_merge_events`` with the ids of what moved, so it can be audited and undone
    (unmerge_guests). The survivor keeps the EARLIER lead identification and first touch of the two, because the person
    was a lead / first heard from at the earlier moment. Returns the merge event (None when there was nothing to do).
    """
    if survivor_id == deprecated_id:
        return None

    from sqlalchemy import text
    from app.core.audit import append_audit
    from app.models.guest import Guest
    from app.models.guest_merge_event import GuestMergeEvent

    survivor = db.query(Guest).filter_by(id=survivor_id, tenant_id=tenant_id).first()
    dep = db.query(Guest).filter_by(id=deprecated_id, tenant_id=tenant_id).first()
    if survivor is None or dep is None:
        raise ValueError("Both guests must belong to this workspace to be merged")
    if dep.deletion_state == "merged":
        return None                       # already merged into someone: safe to call twice

    moved: dict[str, list[str]] = {"identities": []}
    for table in _MOVED_TABLES:
        rows = db.execute(text(f"SELECT id FROM {table} WHERE guest_id = :dep AND tenant_id = :tid"),
                          {"dep": deprecated_id, "tid": tenant_id}).fetchall()
        moved[table] = [r[0] for r in rows]
    before_dep, before_sur = _lead_state(dep), _lead_state(survivor)

    # Re-point all signals from deprecated to survivor
    signals = _signals_for_guest(db, tenant_id, deprecated_id)
    for sig in signals:
        # Check for duplicate type+value on survivor (skip if collision)
        collision = _lookup_signal(db, tenant_id, sig.identity_type, sig.identity_value)
        if collision and collision.guest_id == survivor_id:
            db.delete(sig)
        else:
            moved["identities"].append(sig.id)
            sig.guest_id = survivor_id
            db.add(sig)

    # Re-point related entities
    _repoint_entities(db, tenant_id, deprecated_id, survivor_id)

    # The person was a lead / first heard from at the EARLIER of the two moments.
    if dep.lead_identified_at and (survivor.lead_identified_at is None or dep.lead_identified_at < survivor.lead_identified_at):
        survivor.lead_identified_at, survivor.lead_identified_via = dep.lead_identified_at, dep.lead_identified_via
    if dep.first_touch_at and (survivor.first_touch_at is None or dep.first_touch_at < survivor.first_touch_at):
        survivor.first_touch_at, survivor.first_touch_channel = dep.first_touch_at, dep.first_touch_channel
    if not survivor.phone and dep.phone:
        survivor.phone = dep.phone

    # Soft-delete the deprecated guest
    dep.is_deleted = True
    dep.deletion_state = "merged"
    db.add(dep)
    db.add(survivor)

    event = GuestMergeEvent(
        tenant_id=tenant_id, survivor_id=survivor_id, deprecated_id=deprecated_id, actor_user_id=actor_user_id,
        reason=reason, moved=moved, deprecated_lead_state=before_dep, survivor_lead_state=before_sur,
    )
    db.add(event)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="guest.merged", actor_user_id=actor_user_id, target_type="guest",
                 target_id=survivor_id, payload={"deprecated_id": deprecated_id, "merge_event_id": event.id, "reason": reason,
                                                 "moved": {k: len(v) for k, v in moved.items()}})
    db.commit()
    log.info("guest_merged", survivor=survivor_id, deprecated=deprecated_id, tenant_id=tenant_id, reason=reason)
    return event


def recompute_lead_state(db: Session, tenant_id: str, guest) -> None:
    """Lead state from what the guest owns now: the earliest usable phone signal. Used after an unmerge."""
    times = [s.first_seen_at for s in _signals_for_guest(db, tenant_id, guest.id)
             if s.identity_type in _PHONE_TYPES and s.first_seen_at and phone_identity.normalize(s.identity_value)]
    if times:
        guest.lead_identified_at = min(times)
    elif not phone_identity.normalize(guest.phone or ""):
        guest.lead_identified_at, guest.lead_identified_via = None, None
    db.add(guest)


def unmerge_guests(db: Session, tenant_id: str, merge_event_id: str, *, actor_user_id: Optional[str]):
    """Put back what one merge moved: the deprecated guest comes back, and the identities and records that merge moved
    (and that are still on the survivor) go back to it. Records created after the merge stay where they are."""
    from sqlalchemy import text
    from app.core.audit import append_audit
    from app.models.guest import Guest
    from app.models.guest_merge_event import GuestMergeEvent

    ev = db.query(GuestMergeEvent).filter_by(id=merge_event_id, tenant_id=tenant_id).first()
    if ev is None:
        raise ValueError("Merge not found")
    if ev.unmerged_at is not None:
        raise ValueError("This merge was already undone")
    dep = db.query(Guest).filter_by(id=ev.deprecated_id, tenant_id=tenant_id).first()
    survivor = db.query(Guest).filter_by(id=ev.survivor_id, tenant_id=tenant_id).first()
    if dep is None or survivor is None:
        raise ValueError("A merged guest no longer exists")

    moved = ev.moved or {}
    counts = {}
    for sig in db.query(GuestIdentity).filter(GuestIdentity.tenant_id == tenant_id, GuestIdentity.guest_id == ev.survivor_id,
                                             GuestIdentity.id.in_(moved.get("identities") or ["-"])).all():
        sig.guest_id = ev.deprecated_id
        counts["identities"] = counts.get("identities", 0) + 1
    for table in _MOVED_TABLES:
        for row_id in moved.get(table) or []:
            res = db.execute(text(f"UPDATE {table} SET guest_id = :dep WHERE id = :id AND guest_id = :sur AND tenant_id = :tid"),
                             {"dep": ev.deprecated_id, "sur": ev.survivor_id, "id": row_id, "tid": tenant_id})
            counts[table] = counts.get(table, 0) + (res.rowcount or 0)

    dep.is_deleted, dep.deletion_state = False, "none"
    db.flush()
    recompute_lead_state(db, tenant_id, dep)
    recompute_lead_state(db, tenant_id, survivor)
    for g, before in ((dep, ev.deprecated_lead_state or {}), (survivor, ev.survivor_lead_state or {})):
        g.first_touch_channel = before.get("first_touch_channel")                  # first touch goes back as it was
        g.first_touch_at = datetime.fromisoformat(before["first_touch_at"]) if before.get("first_touch_at") else None
    ev.unmerged_at, ev.unmerged_by = _now(), actor_user_id
    append_audit(db, tenant_id=tenant_id, action="guest.unmerged", actor_user_id=actor_user_id, target_type="guest",
                 target_id=ev.survivor_id, payload={"deprecated_id": ev.deprecated_id, "merge_event_id": ev.id, "restored": counts})
    db.commit()
    log.info("guest_unmerged", survivor=ev.survivor_id, deprecated=ev.deprecated_id, tenant_id=tenant_id)
    return ev


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
        first_touch_channel=channel_for_source(source),     # None = unknown; never guessed
        first_touch_at=_now(),
    )
    db.add(guest)
    db.flush()   # get guest.id without committing

    conf = SIGNAL_CONFIDENCE.get(identity_type, 0.60)
    _attach_signal(db, tenant_id, guest.id, identity_type, identity_value, source, conf)
    db.commit()
    log.info("guest_created", tenant_id=tenant_id, guest_id=guest.id,
             source=source, signal_type=identity_type)
    return guest.id


def _backfill_guest_phone(db: Session, tenant_id: str, guest_id: str, identity_type: str, value: str) -> None:
    """A phone/whatsapp_number signal attached to an ALREADY-EXISTING guest
    (Stage 2 probabilistic match in resolve_or_create, or enrich_guest --
    e.g. a guest who first showed up via Instagram and later calls) never
    backfilled Guest.phone, unlike _create_guest's own new-guest path. The
    convenience column stayed permanently empty even though the phone was
    fully resolvable via guest_identities, which is what every list
    endpoint that reads g.phone directly (list_conversations, calls list,
    etc.) actually displays -- confirmed live: a voice-only inbox card with
    no prior conversation showed no name AND no phone number at all."""
    if identity_type not in (IdentityType.PHONE, IdentityType.WHATSAPP_NUMBER):
        return
    from app.models.guest import Guest
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if guest and not guest.phone:
        guest.phone = value
        db.add(guest)


def _attach_signal(
    db: Session,
    tenant_id: str,
    guest_id: str,
    identity_type: str,
    identity_value: str,
    source: str,
    confidence: float,
    observed_at: Optional[datetime] = None,
) -> GuestIdentity:
    now = observed_at or _now()
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
    _mark_identified(db, tenant_id, guest_id, identity_type, identity_value, source, now)
    return sig


def _mark_identified(db: Session, tenant_id: str, guest_id: str, identity_type: str, value: str,
                     source: str, when: datetime) -> bool:
    """The guest becomes a lead the first time a usable phone number is attached. Set once, never moved. True when it was set."""
    if identity_type not in _PHONE_TYPES or phone_identity.normalize(value) is None:
        return False
    from app.models.guest import Guest
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if guest is None or guest.lead_identified_at is not None:
        return False
    guest.lead_identified_at = when
    guest.lead_identified_via = (channel_for_source(source) or (source or "")[:30] or None)
    db.add(guest)
    return True


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
