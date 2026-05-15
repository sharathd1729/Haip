"""
Hash-chained audit logger.
Every call to append_audit() writes an AuditEvent row whose hash field is:
  sha256(prev_hash + canonical_json(payload))
This creates a tamper-evident chain per tenant.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.models.audit_event import AuditEvent
import structlog

log = structlog.get_logger()


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

    # Fetch last hash for this tenant
    last = (
        db.query(AuditEvent)
        .filter_by(tenant_id=tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    prev_hash = last.hash if last else None

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
    )
    db.add(event)
    log.info("audit_event_appended", tenant_id=tenant_id, action=action, target_id=target_id)
    return event
