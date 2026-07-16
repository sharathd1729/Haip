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
from app.services import leads_service


def _make_tenant(db, name="TenantLeads"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"leads-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


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
    from app.models.conversation import Conversation, Message
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
        channel="whatsapp",
        status="open",
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
            direction="inbound",
            channel="whatsapp",
            body=f"Message {i}",
            created_at=base_time - timedelta(minutes=i),
        )
        db.add(msg)
    db.commit()

    timeline, capped = leads_service.build_timeline(db, tenant.id, inq.id, limit=50)

    assert len(timeline) == 50
    assert capped is True
