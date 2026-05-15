"""Tests for audit event chain integrity."""

import pytest
import uuid


def test_audit_chain_integrity(db, tenant_and_user):
    """
    Append several audit events and verify hash-chain is intact:
    each event's prev_hash equals the sha256 of the previous event's hash.
    """
    from app.core.audit import append_audit
    from app.models.audit_event import AuditEvent
    import hashlib

    tenant_id = tenant_and_user["tenant"].id
    actor_id = tenant_and_user["user"].id

    # Append 3 events
    for i in range(3):
        append_audit(db, actor_id=actor_id, tenant_id=tenant_id,
                     action=f"test_action_{i}", payload={"seq": i})

    events = (
        db.query(AuditEvent)
        .filter_by(tenant_id=tenant_id)
        .order_by(AuditEvent.created_at)
        .all()
    )
    assert len(events) >= 3

    # Verify chain: event[n].prev_hash == event[n-1].event_hash
    for i in range(1, len(events)):
        expected_prev = events[i - 1].event_hash
        assert events[i].prev_hash == expected_prev, (
            f"Chain broken at index {i}: prev_hash {events[i].prev_hash!r} "
            f"!= expected {expected_prev!r}"
        )


def test_audit_list_endpoint(client, tenant_and_user, db):
    """GET /audit/events returns list with correct structure."""
    from app.core.audit import append_audit

    tenant_id = tenant_and_user["tenant"].id
    actor_id = tenant_and_user["user"].id
    token = tenant_and_user["access_token"]

    append_audit(db, actor_id=actor_id, tenant_id=tenant_id,
                 action="login", payload={})

    res = client.get(
        "/api/v1/audit/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    events = res.json()
    assert isinstance(events, list)
    if events:
        assert "action" in events[0]
        assert "created_at" in events[0]
