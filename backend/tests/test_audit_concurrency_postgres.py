"""Audit hash chain under concurrent writers (Phase 0.1, task 3).

append_audit() chains each event to the previous event of the same tenant. It used to read the tail with a plain
SELECT, so two transactions that appended at the same time both read the same tail and both wrote an event
whose prev_hash pointed at it: the chain forked, and tamper evidence broke. A Python lock cannot fix that,
because the writers are different worker processes. The fix is a per-tenant PostgreSQL advisory lock taken
inside the transaction, held until it commits or rolls back.

These tests use real threads with a real connection each against PostgreSQL. They are skipped on SQLite (it has no
advisory locks and no true concurrent writers); CI sets REQUIRE_POSTGRES_TESTS=1, which turns a missing PostgreSQL
into a failure and the skip guard turns any skip into one.
"""
import os
import threading
import time
import uuid

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core import audit as audit_module
from app.core.audit import _compute_hash, append_audit
from app.models.audit_event import AuditEvent
from tests.conftest import TestingSessionLocal, engine

IS_POSTGRES = engine.dialect.name == "postgresql"
pytestmark = pytest.mark.skipif(
    not IS_POSTGRES and os.environ.get("REQUIRE_POSTGRES_TESTS") != "1",
    reason="needs PostgreSQL (advisory locks, concurrent connections). Runs in CI job tenant-isolation-postgres.",
)


def test_postgres_is_available_when_required():
    assert IS_POSTGRES, "REQUIRE_POSTGRES_TESTS=1 but DATABASE_URL is not a PostgreSQL URL"


def _writer(tenant_id, label, events, start, errors, hold=0.0, commit=True):
    """One worker: its own session and transaction appends `events` audit events, then commits (or rolls back)."""
    session = TestingSessionLocal()
    try:
        start.wait(timeout=15)
        for n in range(events):
            append_audit(session, tenant_id=tenant_id, action=f"{label}.{n}", target_id=label, payload={"n": n})
            time.sleep(hold)          # widen the window in which a second writer could read a stale tail
        if commit:
            session.commit()
        else:
            session.rollback()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        errors.append(repr(exc))
    finally:
        session.close()


def _chain(tenant_id):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, action, prev_hash, hash, target_id, payload FROM audit_events WHERE tenant_id = :t"
        ), {"t": tenant_id}).mappings().all()
    return rows


def _cleanup(tenant_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :t"), {"t": tenant_id})


def _assert_single_valid_chain(rows, expected):
    """Exactly one linear chain: one head, every event has one successor, hashes recompute, nothing orphaned."""
    assert len(rows) == expected, f"expected {expected} events, found {len(rows)}"
    heads = [r for r in rows if r["prev_hash"] is None]
    assert len(heads) == 1, f"{len(heads)} events start a chain (a fork or a lost link)"

    children = {}
    for r in rows:
        children.setdefault(r["prev_hash"], []).append(r)
    forks = {k: len(v) for k, v in children.items() if len(v) > 1}
    assert not forks, f"chain forked: {len(forks)} events have more than one successor"

    walked, cursor = [], heads[0]
    while cursor is not None:
        walked.append(cursor)
        nxt = children.get(cursor["hash"], [])
        cursor = nxt[0] if nxt else None
    assert len(walked) == expected, f"chain reaches {len(walked)} of {expected} events"

    for r in rows:
        payload = r["payload"] or {}
        assert r["hash"] == _compute_hash(r["prev_hash"], {"action": r["action"], "target_id": r["target_id"], **payload}), \
            f"hash of {r['action']} does not recompute"


def test_concurrent_transactions_for_one_tenant_form_one_chain():
    tenant_id = f"audit-conc-{uuid.uuid4().hex[:8]}"
    workers, per_worker = 8, 3
    start, errors, threads = threading.Barrier(workers), [], []
    try:
        for i in range(workers):
            t = threading.Thread(target=_writer, args=(tenant_id, f"w{i}", per_worker, start, errors, 0.02))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, errors
        _assert_single_valid_chain(_chain(tenant_id), workers * per_worker)
    finally:
        _cleanup(tenant_id)


def test_different_tenants_do_not_block_each_other_or_share_a_chain():
    a, b = f"audit-a-{uuid.uuid4().hex[:6]}", f"audit-b-{uuid.uuid4().hex[:6]}"
    start, errors, threads = threading.Barrier(4), [], []
    try:
        for tenant, label in ((a, "a1"), (a, "a2"), (b, "b1"), (b, "b2")):
            t = threading.Thread(target=_writer, args=(tenant, label, 3, start, errors, 0.02))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, errors
        _assert_single_valid_chain(_chain(a), 6)
        _assert_single_valid_chain(_chain(b), 6)
    finally:
        _cleanup(a)
        _cleanup(b)


def test_a_rolled_back_writer_leaves_no_link_and_does_not_block_the_next():
    """A transaction that appends and then rolls back must release the lock and must not become anyone's prev_hash."""
    tenant_id = f"audit-rb-{uuid.uuid4().hex[:8]}"
    try:
        seed = TestingSessionLocal()
        append_audit(seed, tenant_id=tenant_id, action="seed")
        seed.commit()
        seed.close()

        start, errors = threading.Barrier(2), []
        aborter = threading.Thread(target=_writer, args=(tenant_id, "abort", 2, start, errors, 0.05, False))
        keeper = threading.Thread(target=_writer, args=(tenant_id, "keep", 2, start, errors, 0.05, True))
        aborter.start(); keeper.start()
        aborter.join(timeout=60); keeper.join(timeout=60)

        assert not errors, errors
        rows = _chain(tenant_id)
        assert {r["action"] for r in rows} == {"seed", "keep.0", "keep.1"}
        _assert_single_valid_chain(rows, 3)
    finally:
        _cleanup(tenant_id)


def test_waiting_for_the_chain_is_bounded(monkeypatch):
    """A writer stuck holding the tenant's chain must not hang other requests forever: the wait times out."""
    tenant_id = f"audit-to-{uuid.uuid4().hex[:8]}"
    holder = TestingSessionLocal()
    try:
        append_audit(holder, tenant_id=tenant_id, action="holds-the-chain")   # lock held until holder ends
        monkeypatch.setattr(audit_module, "LOCK_WAIT", "300ms")
        waiter = TestingSessionLocal()
        started = time.monotonic()
        with structlog.testing.capture_logs() as captured,                 pytest.raises(OperationalError, match="lock timeout|canceling statement") as caught:
            append_audit(waiter, tenant_id=tenant_id, action="waits")
        failures = [e for e in captured if e.get("event") == "audit_chain_lock_failed"]
        assert len(failures) == 1 and failures[0]["pgcode"] == "55P03" and failures[0]["tenant_id"] == tenant_id
        assert time.monotonic() - started < 5, "the wait was not bounded"
        # How the caller sees it: an OperationalError wrapping PostgreSQL's lock_not_available (SQLSTATE 55P03). The
        # transaction is aborted, so the session is unusable until rolled back; after that it works and nothing was written.
        assert caught.value.orig.pgcode == "55P03"
        waiter.rollback()
        assert waiter.execute(text("SELECT 1")).scalar() == 1
        waiter.close()
    finally:
        holder.rollback()
        holder.close()
        _cleanup(tenant_id)


def test_opposite_order_multi_tenant_transactions_deadlock_is_detected_and_a_retry_is_safe():
    """Two transactions that audit the same two tenants in opposite orders deadlock. PostgreSQL detects it (about 1 s,
    deadlock_timeout), aborts exactly one with SQLSTATE 40P01 and the other commits. The loser's whole transaction is
    retried: no event is duplicated or lost and both chains stay single and valid.

    This documents the residual risk of a transaction that audits several tenants (only the two dormant purge jobs do);
    it is why such jobs must use one transaction per tenant rather than one big transaction."""
    a, b = f"audit-dl-a-{uuid.uuid4().hex[:6]}", f"audit-dl-b-{uuid.uuid4().hex[:6]}"
    barrier, outcome = threading.Barrier(2), {}

    def worker(name, first, second):
        session = TestingSessionLocal()
        try:
            append_audit(session, tenant_id=first, action=f"{name}.first")
            barrier.wait(timeout=10)                       # both now hold their first tenant's lock
            append_audit(session, tenant_id=second, action=f"{name}.second")
            session.commit()
            outcome[name] = "committed"
        except OperationalError as exc:
            session.rollback()
            outcome[name] = exc.orig.pgcode
        finally:
            session.close()

    try:
        threads = [threading.Thread(target=worker, args=("w1", a, b)), threading.Thread(target=worker, args=("w2", b, a))]
        with structlog.testing.capture_logs() as captured:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        assert sorted(outcome.values()) == ["40P01", "committed"], f"expected one deadlock victim and one commit: {outcome}"
        deadlock_logs = [e for e in captured if e.get("event") == "audit_chain_lock_failed"]
        assert [e["pgcode"] for e in deadlock_logs] == ["40P01"], "the deadlock must be logged by name, once, for monitoring"

        loser = next(name for name, result in outcome.items() if result == "40P01")
        retry = TestingSessionLocal()
        try:                                               # retry the loser's whole transaction, same order every time
            first, second = (a, b) if loser == "w1" else (b, a)
            append_audit(retry, tenant_id=first, action=f"{loser}.first")
            append_audit(retry, tenant_id=second, action=f"{loser}.second")
            retry.commit()
        finally:
            retry.close()

        for tenant in (a, b):
            rows = _chain(tenant)
            _assert_single_valid_chain(rows, 2)
        actions = sorted(r["action"] for tenant in (a, b) for r in _chain(tenant))
        assert actions == sorted(["w1.first", "w1.second", "w2.first", "w2.second"]), f"duplicated or lost events: {actions}"
    finally:
        _cleanup(a)
        _cleanup(b)
