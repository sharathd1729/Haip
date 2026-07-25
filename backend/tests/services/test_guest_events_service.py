"""
Tests for guest_events_service.py — the unified activity ledger (Phase 1).

  happy path      : record_event writes a row, timelines read it back
  idempotency     : replaying the same source event is a no-op
  tenant isolation: one tenant's ledger never leaks into another's reads
  guest journey   : events across two inquiries land on one guest timeline
  merge           : attach_guest re-points a merged GID's history
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.schemas.guest_events import GuestEventCreate, GuestEventType, SourceModule
from app.services import guest_events_service as ges


def _make_tenant(db, name="TenantEvents"):
    t = Tenant(
        id=str(uuid.uuid4()), name=name,
        slug=f"ev-{uuid.uuid4().hex[:6]}", plan="growth",
    )
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id, name="Event Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g)
    db.flush()
    return g


def _event(**kw) -> GuestEventCreate:
    defaults = dict(
        entity_type="message",
        entity_id=str(uuid.uuid4()),
        event_type=GuestEventType.MESSAGE_RECEIVED,
        source_module=SourceModule.INBOX,
        occurred_at=datetime.now(timezone.utc),
        channel="whatsapp",
        direction="inbound",
        preview="Hello",
    )
    defaults.update(kw)
    return GuestEventCreate(**defaults)


# ── happy path ────────────────────────────────────────────────────────────────

def test_record_event_and_read_guest_timeline(db):
    t = _make_tenant(db)
    g = _make_guest(db, t.id)

    row = ges.record_event(db, t.id, _event(guest_id=g.id, preview="Booking query"))
    assert row is not None

    entries, capped = ges.get_guest_timeline(db, t.id, g.id)
    assert capped is False
    assert len(entries) == 1
    assert entries[0].preview == "Booking query"
    assert entries[0].event_type == GuestEventType.MESSAGE_RECEIVED
    assert entries[0].source_module == SourceModule.INBOX


def test_timeline_is_newest_first_and_caps(db):
    t = _make_tenant(db)
    g = _make_guest(db, t.id)
    base = datetime.now(timezone.utc)

    # 55 events > TIMELINE_CAP of 50
    for i in range(55):
        ges.record_event(
            db, t.id,
            _event(guest_id=g.id, occurred_at=base - timedelta(minutes=i), preview=f"msg-{i}"),
        )

    entries, capped = ges.get_guest_timeline(db, t.id, g.id)
    assert capped is True
    assert len(entries) == ges.TIMELINE_CAP
    assert entries[0].preview == "msg-0"          # newest first
    assert entries[0].occurred_at >= entries[-1].occurred_at


# ── idempotency ───────────────────────────────────────────────────────────────

def test_replaying_same_event_is_a_noop(db):
    """The backfill re-running over rows a live write already recorded must not
    duplicate them, and must leave the session usable."""
    t = _make_tenant(db)
    g = _make_guest(db, t.id)
    msg_id = str(uuid.uuid4())

    first = ges.record_event(db, t.id, _event(guest_id=g.id, entity_id=msg_id))
    second = ges.record_event(db, t.id, _event(guest_id=g.id, entity_id=msg_id))

    assert first is not None
    assert second is None, "duplicate should be ignored, not inserted"

    entries, _ = ges.get_guest_timeline(db, t.id, g.id)
    assert len(entries) == 1

    # The failed insert must not have poisoned the transaction.
    assert ges.record_event(db, t.id, _event(guest_id=g.id)) is not None


def test_same_entity_different_event_type_both_recorded(db):
    """A call is both 'completed' and later 'analyzed' — the dedup key is
    scoped per event_type, so both belong on the timeline."""
    t = _make_tenant(db)
    g = _make_guest(db, t.id)
    call_id = str(uuid.uuid4())

    a = ges.record_event(db, t.id, _event(
        guest_id=g.id, entity_type="call", entity_id=call_id,
        event_type=GuestEventType.CALL_COMPLETED, source_module=SourceModule.CALLS,
    ))
    b = ges.record_event(db, t.id, _event(
        guest_id=g.id, entity_type="call", entity_id=call_id,
        event_type=GuestEventType.CALL_ANALYZED, source_module=SourceModule.CALLS,
    ))

    assert a is not None and b is not None
    entries, _ = ges.get_guest_timeline(db, t.id, g.id)
    assert len(entries) == 2


# ── tenant isolation ──────────────────────────────────────────────────────────

def test_guest_timeline_is_tenant_isolated(db):
    t1, t2 = _make_tenant(db, "T1"), _make_tenant(db, "T2")
    g1, g2 = _make_guest(db, t1.id), _make_guest(db, t2.id)

    ges.record_event(db, t1.id, _event(guest_id=g1.id, preview="tenant-1 only"))
    ges.record_event(db, t2.id, _event(guest_id=g2.id, preview="tenant-2 only"))

    e1, _ = ges.get_guest_timeline(db, t1.id, g1.id)
    e2, _ = ges.get_guest_timeline(db, t2.id, g2.id)
    assert [e.preview for e in e1] == ["tenant-1 only"]
    assert [e.preview for e in e2] == ["tenant-2 only"]

    # Reading another tenant's guest id under your own tenant returns nothing.
    cross, _ = ges.get_guest_timeline(db, t1.id, g2.id)
    assert cross == []


def test_inquiry_timeline_is_tenant_isolated(db):
    t1, t2 = _make_tenant(db, "T1"), _make_tenant(db, "T2")
    shared_inquiry_id = str(uuid.uuid4())  # same id, different tenants

    ges.record_event(db, t1.id, _event(inquiry_id=shared_inquiry_id, preview="t1"))
    ges.record_event(db, t2.id, _event(inquiry_id=shared_inquiry_id, preview="t2"))

    e1, _ = ges.get_inquiry_timeline(db, t1.id, shared_inquiry_id)
    assert [e.preview for e in e1] == ["t1"]


# ── guest journey across inquiries ────────────────────────────────────────────

def test_guest_timeline_spans_multiple_inquiries(db):
    """The gap the old per-inquiry build_timeline() could not fill."""
    t = _make_tenant(db)
    g = _make_guest(db, t.id)
    inq_a, inq_b = str(uuid.uuid4()), str(uuid.uuid4())

    ges.record_event(db, t.id, _event(guest_id=g.id, inquiry_id=inq_a, preview="first stay"))
    ges.record_event(db, t.id, _event(guest_id=g.id, inquiry_id=inq_b, preview="repeat booking"))

    entries, _ = ges.get_guest_timeline(db, t.id, g.id)
    assert len(entries) == 2
    assert {e.inquiry_id for e in entries} == {inq_a, inq_b}

    only_a, _ = ges.get_inquiry_timeline(db, t.id, inq_a)
    assert len(only_a) == 1


# ── merge ─────────────────────────────────────────────────────────────────────

def test_attach_guest_repoints_history_on_merge(db):
    t = _make_tenant(db)
    losing, surviving = _make_guest(db, t.id, "dupe"), _make_guest(db, t.id, "canonical")

    ges.record_event(db, t.id, _event(guest_id=losing.id, preview="pre-merge"))
    ges.record_event(db, t.id, _event(guest_id=surviving.id, preview="existing"))

    moved = ges.attach_guest(db, t.id, from_guest_id=losing.id, to_guest_id=surviving.id)
    assert moved == 1

    entries, _ = ges.get_guest_timeline(db, t.id, surviving.id)
    assert {e.preview for e in entries} == {"pre-merge", "existing"}
    assert ges.get_guest_timeline(db, t.id, losing.id)[0] == []
