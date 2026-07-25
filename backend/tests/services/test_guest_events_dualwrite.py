"""
Phase 1 dual-write integration — proves the ledger is populated by the real
service paths, not just by direct record_event() calls.

  inquiry_service.update_stage        → legacy enum path writes to the ledger
  inquiry_service.update_stage_by_id  → stage_id path writes to the ledger
  identity_service.merge_guests       → merged guest's history follows survivor

Both transition paths are covered deliberately: they are separate functions
with separate stage-log writes, so a hook added to only one silently drops
every transition that goes through the other.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.schemas.guest_events import GuestEventCreate, GuestEventType, SourceModule
from app.services import guest_events_service as ges
from app.services import inquiry_service, identity_service


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="DW",
               slug=f"dw-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    return t


def _guest(db, tenant_id, name="G"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g); db.flush()
    return g


def _inquiry(db, tenant_id, guest_id):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        stage=InquiryStage.NEW, source=InquirySource.META_IG,
    )
    db.add(inq); db.flush()
    return inq


def test_stage_transition_writes_to_ledger(db):
    t = _tenant(db)
    g = _guest(db, t.id)
    inq = _inquiry(db, t.id, g.id)

    inquiry_service.update_stage(
        db, tenant_id=t.id, inquiry_id=inq.id,
        new_stage=InquiryStage.RESPONDING, actor_user_id="user-1", actor_role="owner",
    )
    db.flush()

    entries, _ = ges.get_inquiry_timeline(db, t.id, inq.id)
    moves = [e for e in entries if e.event_type == GuestEventType.INQUIRY_STAGE_MOVED]
    assert len(moves) == 1

    ev = moves[0]
    assert ev.guest_id == g.id
    assert ev.payload["from_stage"] == InquiryStage.NEW.value
    assert ev.payload["to_stage"] == InquiryStage.RESPONDING.value
    assert ev.actor_user_id == "user-1"

    # The same event is reachable from the guest-level journey.
    guest_entries, _ = ges.get_guest_timeline(db, t.id, g.id)
    assert any(e.event_type == GuestEventType.INQUIRY_STAGE_MOVED for e in guest_entries)


def test_stage_transition_by_id_writes_to_ledger(db):
    """The stage_id path (pipeline_stages catalog) must hit the ledger too —
    this is the path Leads360 actually uses post-restructure."""
    from app.models.pipeline_stage import PipelineStage

    t = _tenant(db)
    g = _guest(db, t.id)
    inq = _inquiry(db, t.id, g.id)

    def _stage(key, label, order, **flags):
        s = PipelineStage(
            id=str(uuid.uuid4()), tenant_id=t.id, key=key, label=label,
            color="#6366f1", order=order, category=flags.pop("category", "valid"), **flags,
        )
        db.add(s); db.flush()
        return s

    from_stage = _stage("general_enquiry", "General Enquiry", 0,
                        category="invalid", is_default_entry=True)
    to_stage = _stage("active", "Active", 1, is_valid_lead_entry=True)

    inq.stage_id = from_stage.id
    db.flush()

    inquiry_service.update_stage_by_id(
        db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=to_stage.id,
        actor_user_id="user-2", actor_role="owner",
    )
    db.flush()

    entries, _ = ges.get_inquiry_timeline(db, t.id, inq.id)
    moves = [e for e in entries if e.event_type == GuestEventType.INQUIRY_STAGE_MOVED]
    assert len(moves) == 1, "stage_id transition must land on the ledger"

    ev = moves[0]
    assert ev.payload["from_stage"] == "general_enquiry"
    assert ev.payload["to_stage"] == "active"
    assert ev.guest_id == g.id


def test_ledger_failure_does_not_block_stage_transition(db, monkeypatch):
    """The dual-write is best-effort by design — a broken ledger must not stop
    the business operation."""
    t = _tenant(db)
    g = _guest(db, t.id)
    inq = _inquiry(db, t.id, g.id)

    def _boom(*a, **kw):
        raise RuntimeError("ledger down")

    monkeypatch.setattr("app.core.events.emit_event", _boom)

    inquiry_service.update_stage(
        db, tenant_id=t.id, inquiry_id=inq.id,
        new_stage=InquiryStage.RESPONDING, actor_user_id="user-1", actor_role="owner",
    )
    db.flush()

    assert inq.stage == InquiryStage.RESPONDING


def test_merge_moves_history_to_surviving_guest(db):
    t = _tenant(db)
    survivor = _guest(db, t.id, "canonical")
    deprecated = _guest(db, t.id, "duplicate")

    # History on the guest that is about to be merged away.
    ges.record_event(db, t.id, GuestEventCreate(
        guest_id=deprecated.id,
        entity_type="message",
        entity_id=str(uuid.uuid4()),
        event_type=GuestEventType.MESSAGE_RECEIVED,
        source_module=SourceModule.INBOX,
        occurred_at=datetime.now(timezone.utc),
        preview="from the duplicate record",
    ))
    db.flush()

    identity_service.merge_guests(
        db, tenant_id=t.id, survivor_id=survivor.id, deprecated_id=deprecated.id
    )
    db.flush()

    entries, _ = ges.get_guest_timeline(db, t.id, survivor.id)
    previews = {e.preview for e in entries}
    assert "from the duplicate record" in previews, (
        "merged guest's history must follow the survivor"
    )
    # Nothing left stranded on the deprecated GID.
    orphaned, _ = ges.get_guest_timeline(db, t.id, deprecated.id)
    assert orphaned == []
