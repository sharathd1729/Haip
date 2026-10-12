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
        append_audit(db, actor_user_id=actor_id, tenant_id=tenant_id,
                     action=f"test_action_{i}", payload={"seq": i})
    db.commit()  # append_audit leaves committing to the caller

    events = (
        db.query(AuditEvent)
        .filter_by(tenant_id=tenant_id)
        .order_by(AuditEvent.created_at)
        .all()
    )
    assert len(events) >= 3

    # Verify chain: event[n].prev_hash == event[n-1].hash
    for i in range(1, len(events)):
        expected_prev = events[i - 1].hash
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

    append_audit(db, actor_user_id=actor_id, tenant_id=tenant_id,
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


def _tenant(db, name):
    from app.models.tenant import Tenant
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def test_chain_hashes_recompute_and_link_within_one_transaction(db):
    """Regression: several appends before a single commit must form one chain (they used to fork,
    each starting from the old tail), and every hash must be the sha256 of prev_hash + payload."""
    from app.core.audit import append_audit, _compute_hash
    from app.models.audit_event import AuditEvent

    t = _tenant(db, "chain")
    for i in range(4):
        append_audit(db, tenant_id=t.id, action=f"a{i}", target_id=f"t{i}", payload={"n": i})
    db.commit()

    events = db.query(AuditEvent).filter_by(tenant_id=t.id).order_by(AuditEvent.created_at).all()
    assert len(events) == 4
    assert events[0].prev_hash is None
    for prev, ev in zip(events, events[1:]):
        assert ev.prev_hash == prev.hash
    for ev in events:
        assert ev.hash == _compute_hash(ev.prev_hash, {"action": ev.action, "target_id": ev.target_id, **ev.payload})


def test_chains_are_per_tenant(db):
    """One tenant's events never become another tenant's prev_hash."""
    from app.core.audit import append_audit

    a, b = _tenant(db, "a"), _tenant(db, "b")
    ea = append_audit(db, tenant_id=a.id, action="x")
    eb = append_audit(db, tenant_id=b.id, action="y")
    ea2 = append_audit(db, tenant_id=a.id, action="z")
    db.commit()

    assert eb.prev_hash is None, "tenant B starts its own chain"
    assert ea2.prev_hash == ea.hash


def test_rolled_back_event_is_not_chained_to(db):
    """After a rollback the discarded event must not become the next event's prev_hash."""
    from app.core.audit import append_audit

    t = _tenant(db, "rb")
    db.commit()
    first = append_audit(db, tenant_id=t.id, action="kept")
    db.commit()
    savepoint = db.begin_nested()      # the per-test session wraps an outer transaction, so use a savepoint
    append_audit(db, tenant_id=t.id, action="discarded")
    savepoint.rollback()
    nxt = append_audit(db, tenant_id=t.id, action="after")
    db.commit()

    assert nxt.prev_hash == first.hash


def test_the_tail_is_unambiguous_even_when_the_clock_does_not_move(db, monkeypatch):
    """Regression (Phase 0.1): the tail is chosen by created_at. Events flushed together, or written within one clock
    tick by different processes, shared a timestamp, so the next writer could chain to the wrong event and fork the
    chain. Each event must be stamped strictly after the previous one even if the clock reports the same instant."""
    from datetime import datetime, timezone

    from app.core import audit as audit_module
    from app.core.audit import append_audit
    from app.models.audit_event import AuditEvent

    frozen = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(audit_module, "datetime", _FrozenClock)
    t = _tenant(db, "tie")
    first = [append_audit(db, tenant_id=t.id, action=f"a{i}") for i in range(3)]
    db.commit()
    later = append_audit(db, tenant_id=t.id, action="next-transaction")    # reads the tail from the database
    db.commit()

    stamps = [e.created_at for e in first] + [later.created_at]
    assert stamps == sorted(set(stamps)), f"timestamps must be strictly increasing, got {stamps}"
    assert later.prev_hash == first[-1].hash, "the next writer must chain to the LAST event, not an arbitrary one of a tie"
    events = db.query(AuditEvent).filter_by(tenant_id=t.id).order_by(AuditEvent.created_at).all()
    assert [e.prev_hash for e in events[1:]] == [e.hash for e in events[:-1]]
