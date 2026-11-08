"""
Tests for leads_service.py — T22, T23, T24, T25

Tests:
  T22: get_leads_pipeline — guest with 2 inquiries → 2 rows
  T23: profile_completeness — IG-only guest → 30%
  T24: profile_completeness — IG + WA guest → 60%
  T25: build_timeline — 60 events → capped at 50, timeline_capped=True
"""

import uuid
import pytest

from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.guest_identity import GuestIdentity
from app.models.pipeline_stage import PipelineStage
from app.models.user import User, UserRole
from app.services import leads_service


def _make_tenant(db, name="TenantLeads"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"leads-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_agent(db, tenant_id, name):
    """A real agent: inquiries.assigned_to is a foreign key to users, enforced by PostgreSQL."""
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@test.com",
             hashed_password="x", role=UserRole.CONCIERGE, is_active=True)
    db.add(u)
    db.flush()
    return u


def _make_guest(db, tenant_id, name="Test Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g)
    db.flush()
    return g


def _make_inquiry(db, tenant_id, guest_id, stage=InquiryStage.NEW, source=InquirySource.META_IG):
    inq = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest_id,
        stage=stage,
        source=source,
    )
    db.add(inq)
    db.flush()
    return inq


def _add_signal(db, tenant_id, guest_id, identity_type, value, confidence=0.70):
    from app.models.base import gen_uuid
    sig = GuestIdentity(
        id=gen_uuid(),
        tenant_id=tenant_id,
        guest_id=guest_id,
        identity_type=identity_type,
        identity_value=value,
        source="test",
        confidence=confidence,
    )
    db.add(sig)
    db.flush()
    return sig


def _make_stage(db, tenant_id, key, order=0, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


# ── stage filter must key off pipeline_stages, not the legacy enum ─────────
# Regression coverage: get_leads_pipeline's `stage` filter used to compare
# directly against the legacy Inquiry.stage enum column. That only worked by
# coincidence for tenants whose custom stage keys happened to equal old enum
# values (new/responding/...) -- any tenant-custom or new-taxonomy key
# (e.g. "active", "general_enquiry") silently matched zero rows. Discovered
# live against Ratha's production board after the 049 taxonomy rework: every
# column showed "No leads here" despite 50 backfilled inquiries existing.

def test_get_leads_pipeline_filters_by_tenant_custom_stage_key(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    active_stage = _make_stage(db, tenant.id, "active", 0)
    other_stage = _make_stage(db, tenant.id, "general_enquiry", 1)

    matching = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    matching.stage_id = active_stage.id
    non_matching = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    non_matching.stage_id = other_stage.id
    db.flush()

    result = leads_service.get_leads_pipeline(db, tenant.id, stage="active")

    ids = [row.inquiry_id for row in result.leads]
    assert matching.id in ids
    assert non_matching.id not in ids


def test_get_leads_pipeline_unknown_stage_key_returns_empty_not_error(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    stage = _make_stage(db, tenant.id, "active", 0)
    inq = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    inq.stage_id = stage.id
    db.flush()

    result = leads_service.get_leads_pipeline(db, tenant.id, stage="does_not_exist")

    assert result.leads == []
    assert result.total == 0


def test_get_leads_pipeline_legacy_enum_key_still_works(db):
    """Back-compat: a stage string that isn't any tenant's pipeline_stages
    key, but IS a valid legacy InquiryStage enum value, still filters
    correctly (covers any caller still on the old enum-value stage keys)."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    matching = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.RESPONDING)
    non_matching = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)

    result = leads_service.get_leads_pipeline(db, tenant.id, stage="responding")

    ids = [row.inquiry_id for row in result.leads]
    assert matching.id in ids
    assert non_matching.id not in ids


# ── card/summary payload must key off pipeline_stages.key, not the enum ────
# Regression coverage for the second half of the same bug class: the board's
# initial unfiltered load groups cards client-side using LeadCardSchema's
# stage_key field, and the stage-filter pill counts come from
# _build_stage_summary()'s grouping -- both previously kept using the legacy
# Inquiry.stage enum, so every card/column silently mismatched under any
# tenant-custom or new-taxonomy stage key even though get_leads_pipeline's
# `stage` *filter* param (tested above) was already fixed.

def test_build_lead_card_populates_stage_key_from_pipeline_stage(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    active_stage = _make_stage(db, tenant.id, "active", 0)
    inq = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    inq.stage_id = active_stage.id
    db.flush()

    result = leads_service.get_leads_pipeline(db, tenant.id)

    card = next(c for c in result.leads if c.inquiry_id == inq.id)
    assert card.stage_key == "active"


def test_build_lead_card_stage_key_none_when_stage_id_unset(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    inq = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    db.flush()

    result = leads_service.get_leads_pipeline(db, tenant.id)

    card = next(c for c in result.leads if c.inquiry_id == inq.id)
    assert card.stage_key is None


def test_stage_summary_groups_by_pipeline_stage_key(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    active_stage = _make_stage(db, tenant.id, "active", 0)
    general_stage = _make_stage(db, tenant.id, "general_enquiry", 1)

    inq1 = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    inq1.stage_id = active_stage.id
    inq2 = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    inq2.stage_id = active_stage.id
    inq3 = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    inq3.stage_id = general_stage.id
    db.flush()

    result = leads_service.get_leads_pipeline(db, tenant.id)

    assert result.stages["active"].count == 2
    assert result.stages["general_enquiry"].count == 1
    assert "new" not in result.stages  # not grouped by the legacy enum value


# ── Regression: stage count badge must match the card list's qualification
# filter. get_leads_pipeline's card list excludes qualification_status ==
# "unqualified" (leads_service.py ~L541), but _build_stage_summary's count
# query didn't apply the same filter -- so a column like
# "collaboration_engagement" could show a nonzero count badge while its card
# list rendered "No leads here", since every inquiry landing there defaults
# to qualification_status="unqualified". Discovered live on Ratha's board.
def test_stage_summary_excludes_unqualified_like_the_card_list(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    collab_stage = _make_stage(db, tenant.id, "collaboration_engagement", 0)

    inq = _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    inq.stage_id = collab_stage.id
    inq.qualification_status = "unqualified"
    db.flush()

    result = leads_service.get_leads_pipeline(db, tenant.id)

    assert "collaboration_engagement" not in result.stages or \
        result.stages["collaboration_engagement"].count == 0
    assert not any(c.inquiry_id == inq.id for c in result.leads)


# ── T22: one inquiry = one lead card ─────────────────────────────────────────

def test_get_leads_pipeline_one_row_per_inquiry(db):
    """A guest with 2 open inquiries appears as 2 separate rows."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.NEW)
    _make_inquiry(db, tenant.id, guest.id, stage=InquiryStage.RESPONDING)
    db.commit()

    result = leads_service.get_leads_pipeline(db=db, tenant_id=tenant.id)

    assert result.total == 2
    assert len(result.leads) == 2
    # Both cards reference the same guest
    guest_ids = {card.guest_id for card in result.leads}
    assert guest_ids == {guest.id}
    # But different inquiry IDs
    inquiry_ids = {card.inquiry_id for card in result.leads}
    assert len(inquiry_ids) == 2


# ── scope_user_id: non-owner/manager visibility guard ────────────────────────

def test_scope_user_id_hides_peer_agents_leads(db):
    """Krisha/Jishant case: an agent scoped to their own id must not see a
    lead assigned to a different agent, only their own + unclaimed ones."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    jishant, krisha = _make_agent(db, tenant.id, "Jishant"), _make_agent(db, tenant.id, "Krisha")
    mine = _make_inquiry(db, tenant.id, guest.id)
    mine.assigned_to = jishant.id
    theirs = _make_inquiry(db, tenant.id, guest.id)
    theirs.assigned_to = krisha.id
    unclaimed = _make_inquiry(db, tenant.id, guest.id)
    db.commit()

    result = leads_service.get_leads_pipeline(db=db, tenant_id=tenant.id, scope_user_id=jishant.id)

    visible_ids = {card.inquiry_id for card in result.leads}
    assert visible_ids == {mine.id, unclaimed.id}
    assert theirs.id not in visible_ids


def test_scope_user_id_none_sees_everything(db):
    """Owner/manager pass scope_user_id=None -- unchanged tenant-wide view."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    a = _make_inquiry(db, tenant.id, guest.id)
    a.assigned_to = _make_agent(db, tenant.id, "AgentA").id
    b = _make_inquiry(db, tenant.id, guest.id)
    b.assigned_to = _make_agent(db, tenant.id, "AgentB").id
    db.commit()

    result = leads_service.get_leads_pipeline(db=db, tenant_id=tenant.id, scope_user_id=None)
    assert {card.inquiry_id for card in result.leads} == {a.id, b.id}


def test_get_lead_detail_scoped_agent_cannot_open_peers_lead(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    jishant, krisha = _make_agent(db, tenant.id, "Jishant"), _make_agent(db, tenant.id, "Krisha")
    theirs = _make_inquiry(db, tenant.id, guest.id)
    theirs.assigned_to = krisha.id
    db.commit()

    assert leads_service.get_lead_detail(db, tenant.id, theirs.id, scope_user_id=jishant.id) is None
    assert leads_service.get_lead_detail(db, tenant.id, theirs.id, scope_user_id=krisha.id) is not None
    assert leads_service.get_lead_detail(db, tenant.id, theirs.id, scope_user_id=None) is not None


# ── T23: profile completeness IG-only → 30% ──────────────────────────────────

def test_profile_completeness_ig_only(db):
    """Guest with only instagram_user_id signal → completeness = 30."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    _add_signal(db, tenant.id, guest.id, "instagram_user_id", "ig_user_999")
    db.commit()

    result = leads_service.get_profile_completeness(db, tenant.id, guest.id)
    assert result == 30


# ── T24: profile completeness IG + WA → 60% ──────────────────────────────────

def test_profile_completeness_ig_plus_wa(db):
    """Guest with instagram_user_id + whatsapp_number → completeness = 60."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    _add_signal(db, tenant.id, guest.id, "instagram_user_id", "ig_user_777")
    _add_signal(db, tenant.id, guest.id, "whatsapp_number", "+919000000001", confidence=0.85)
    db.commit()

    result = leads_service.get_profile_completeness(db, tenant.id, guest.id)
    assert result == 60


# ── T25: timeline capped at 50 ───────────────────────────────────────────────

def test_build_timeline_cap(db):
    """60 timeline events → capped at 50 entries, timeline_capped=True."""
    from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
    from datetime import datetime, timezone, timedelta

    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    inq = _make_inquiry(db, tenant.id, guest.id)

    # Create a conversation linked to the inquiry
    conv = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        guest_id=guest.id,
        inquiry_id=inq.id,
        channel=ChannelType.WHATSAPP,
        is_open=True,
    )
    db.add(conv)
    db.flush()

    # Add 60 messages
    base_time = datetime.now(timezone.utc)
    for i in range(60):
        msg = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            channel=ChannelType.WHATSAPP,
            body=f"Message {i}",
            created_at=base_time - timedelta(minutes=i),
        )
        db.add(msg)
    db.commit()

    timeline, capped = leads_service.build_timeline(db, tenant.id, inq.id, limit=50)

    assert len(timeline) == 50
    assert capped is True


# ── trigger_summary_refresh: one trailing run per message burst ──────────────
# AI cost audit (8 Nov 2026): a burst used to cost an immediate run AND a trailing one. Now the first message schedules ONE
# run at the end of the window and the rest of the burst is absorbed by it (the task reads the DB when it runs, so a second
# message with the dates is still in it). Calls run at once (end of wrap_up); a manual refresh at once, 2-min cooldown.

def _fake_cache(monkeypatch, module):
    """In-memory Redis stand-in: get_cached/set_cached fail open to None on a real Redis outage, which would make every
    debounce assertion here vacuously pass."""
    store: dict = {}

    def _get(key):
        return store.get(key)

    def _set(key, value, ttl=300):
        store[key] = value

    monkeypatch.setattr(module, "get_cached", _get)
    monkeypatch.setattr(module, "set_cached", _set)
    return store


def _capture(monkeypatch):
    immediate, scheduled = [], []
    monkeypatch.setattr("app.workers.tasks.generate_ai_summary.generate_ai_summary.delay",
                        lambda **kw: immediate.append(kw))
    monkeypatch.setattr("app.workers.tasks.generate_ai_summary.generate_ai_summary.apply_async",
                        lambda **kw: scheduled.append(kw))
    return immediate, scheduled


class TestTriggerSummaryRefreshBurst:
    def test_burst_gets_one_trailing_run_and_nothing_immediate(self, db, monkeypatch):
        _fake_cache(monkeypatch, leads_service)
        immediate, scheduled = _capture(monkeypatch)

        fired = [leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="message") for _ in range(3)]

        assert fired == [True, False, False]
        assert immediate == []
        assert scheduled == [{"kwargs": {"inquiry_id": "inq-1", "tenant_id": "tenant-1"},
                              "countdown": leads_service.SUMMARY_DEBOUNCE_TTL}]

    def test_call_source_fires_immediately_even_inside_a_burst(self, db, monkeypatch):
        _fake_cache(monkeypatch, leads_service)
        immediate, scheduled = _capture(monkeypatch)

        leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="message")
        assert leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="call") is True
        assert immediate == [{"inquiry_id": "inq-1", "tenant_id": "tenant-1"}]
        assert len(scheduled) == 1

    def test_manual_fires_with_force_then_cools_down(self, db, monkeypatch):
        store = _fake_cache(monkeypatch, leads_service)
        immediate, _ = _capture(monkeypatch)

        first = leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="manual")
        second = leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="manual")
        other = leads_service.trigger_summary_refresh(db, "inq-2", "tenant-1", source="manual")

        assert (first, second, other) == (True, False, True)
        assert immediate == [{"inquiry_id": "inq-1", "tenant_id": "tenant-1", "force": True},
                             {"inquiry_id": "inq-2", "tenant_id": "tenant-1", "force": True}]
        store.clear()                                   # cooldown over
        assert leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="manual") is True

    def test_burst_isolated_per_inquiry_and_tenant(self, db, monkeypatch):
        _fake_cache(monkeypatch, leads_service)
        _, scheduled = _capture(monkeypatch)

        leads_service.trigger_summary_refresh(db, "inq-1", "tenant-1", source="message")
        assert leads_service.trigger_summary_refresh(db, "inq-2", "tenant-1", source="message") is True
        assert leads_service.trigger_summary_refresh(db, "inq-1", "tenant-2", source="message") is True
        assert len(scheduled) == 3
