"""
Hash-chained audit logger.
Every call to append_audit() writes an AuditEvent row whose hash field is:
  sha256(prev_hash + canonical_json(payload))
This creates a tamper-evident chain per tenant.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.models.audit_event import AuditEvent
import structlog

log = structlog.get_logger()


_PENDING_KEY = "audit_pending_tail"

# How long a writer waits for another transaction that is appending to the same tenant's chain. Bounded so a
# stuck transaction cannot hang every request that writes an audit event for that tenant.
LOCK_WAIT = "10s"

# Actors that are not rows in `users` (audit_events.actor_user_id is a foreign key to users.id). Their events are
# stored with a NULL user and the actor's name in payload["actor"], so the chain still says who acted.
NON_USER_ACTORS = frozenset({"agency", "system"})


def _lock_chain(db: Session, tenant_id: str) -> None:
    """Serialise appends to one tenant's chain across every worker process (PostgreSQL only).

    The previous hash is read from the database, so two transactions that append at the same time would both
    read the same tail and fork the chain. A transaction-scoped advisory lock keyed on the tenant makes the second
    writer wait until the first commits or rolls back, then read the tail the first one left. The lock is released
    automatically at commit/rollback, so a crashed or rolled-back writer cannot leave it held, and a retry simply
    takes it again. It is re-entrant, so several appends in one transaction are fine.

    Costs and rules (see docs/HAIP_Phase0_Failure_Register.md): the lock is held until the caller commits, so
    callers should append close to their commit; a transaction that appends for several tenants should do so in a
    consistent order (PostgreSQL detects a deadlock and aborts one side, which the caller then retries).
    """
    if db.get_bind().dialect.name != "postgresql":
        return  # SQLite: single writer at a time, and no advisory locks
    previous = db.execute(text("SELECT current_setting('lock_timeout')")).scalar()
    db.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": LOCK_WAIT})
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"haip.audit:{tenant_id}"})
    except OperationalError as exc:
        # 55P03 = waited longer than LOCK_WAIT for another writer; 40P01 = deadlock (this transaction is the victim).
        # Raised unchanged for the caller, who must roll back; logged by name so it can be searched and alerted on
        # (it would otherwise only appear as a generic traceback and an HTTP 500). Carries no personal data.
        log.warning("audit_chain_lock_failed", tenant_id=tenant_id, pgcode=getattr(exc.orig, "pgcode", None), wait=LOCK_WAIT)
        raise
    db.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": previous})


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: Optional[str], payload: Any) -> str:
    prev = prev_hash or ""
    data = prev + _canonical(payload)
    return hashlib.sha256(data.encode()).hexdigest()


def append_audit(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    actor_user_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> AuditEvent:
    """
    Append an audit event to the hash chain for this tenant.
    Must be called within an open db session; caller commits.
    """
    payload = payload or {}
    if actor_user_id in NON_USER_ACTORS:
        payload = {**payload, "actor": actor_user_id}
        actor_user_id = None

    _lock_chain(db, tenant_id)   # before reading the tail, so a concurrent writer's committed event is visible

    # Sessions run with autoflush off, so an event appended earlier in this same transaction is
    # invisible to a query. Chain from it directly while it is still pending; otherwise two
    # appends before one commit would both start from the old tail and fork the chain.
    pending = db.info.get(_PENDING_KEY, {}).get(tenant_id)
    if pending is not None and sa_inspect(pending).pending:
        prev_hash, prev_at = pending.hash, pending.created_at
    else:
        last = (
            db.query(AuditEvent)
            .filter_by(tenant_id=tenant_id)
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        prev_hash, prev_at = (last.hash, last.created_at) if last else (None, None)

    # The tail is chosen by created_at, so created_at must be strictly increasing per tenant. Events flushed
    # together (or written by different processes within one clock tick) used to share a timestamp, and the next
    # writer could then pick the wrong "last" event and fork the chain even with the lock held. Under the lock
    # nothing newer can exist, so the new event is stamped after the tail.
    created_at = datetime.now(timezone.utc)
    if prev_at is not None:
        if prev_at.tzinfo is None:
            prev_at = prev_at.replace(tzinfo=timezone.utc)
        if created_at <= prev_at:
            created_at = prev_at + timedelta(microseconds=1)

    h = _compute_hash(prev_hash, {"action": action, "target_id": target_id, **payload})

    event = AuditEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        prev_hash=prev_hash,
        hash=h,
        created_at=created_at,
    )
    db.add(event)
    db.info.setdefault(_PENDING_KEY, {})[tenant_id] = event
    log.info("audit_event_appended", tenant_id=tenant_id, action=action, target_id=target_id)
    return event
