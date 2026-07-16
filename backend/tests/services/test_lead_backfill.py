"""
Tests for lead_backfill.py -- one-time remediation creating Leads360
inquiries for WhatsApp/Instagram conversations that pre-date the chat
auto-create wiring (which only fires on a genuinely new conversation).
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.pipeline_stage import PipelineStage
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.services.lead_backfill import backfill_tenant_leads_from_conversations


def _make_tenant(db, name="TenantBackfill"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"bf-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_stage(db, tenant_id, key, order, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


def _make_guest(db, tenant_id, name="Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g)
    db.flush()
    return g


def _make_conversation(db, tenant_id, guest_id, channel, inquiry_id=None):
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, channel=channel, inquiry_id=inquiry_id)
    db.add(c)
    db.flush()
    return c


def _make_message(db, tenant_id, conversation_id, channel, body, direction=MessageDirection.INBOUND, minutes_ago=0):
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction=direction, channel=channel, body=body,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(m)
    db.flush()
    return m


def _default_stages(db, tenant_id):
    _make_stage(db, tenant_id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    valid = _make_stage(db, tenant_id, "active", 1, category="valid", is_valid_lead_entry=True)
    collab = _make_stage(db, tenant_id, "collaboration_engagement", 2, category="marketing", is_collab_entry=True)
    return valid, collab


def test_backfill_creates_inquiry_from_earliest_message(db):
    t = _make_tenant(db)
    valid, _ = _default_stages(db, t.id)
    guest = _make_guest(db, t.id)
    convo = _make_conversation(db, t.id, guest.id, ChannelType.WHATSAPP)
    _make_message(db, t.id, convo.id, ChannelType.WHATSAPP, "hi, is the villa free?", minutes_ago=10)
    _make_message(db, t.id, convo.id, ChannelType.WHATSAPP, "second message", minutes_ago=1)

    stats = backfill_tenant_leads_from_conversations(db, t.id)

    assert stats["guests_processed"] == 1
    assert stats["inquiries_created"] == 1
    assert stats["conversations_linked"] == 1

    inquiry = db.query(Inquiry).filter_by(tenant_id=t.id, guest_id=guest.id).first()
    assert inquiry is not None
    assert inquiry.stage_id == valid.id
    assert inquiry.source == InquirySource.WA_DIRECT

    db.refresh(convo)
    assert convo.inquiry_id == inquiry.id


def test_backfill_routes_collab_keyword_to_collab_stage(db):
    t = _make_tenant(db)
    _default_stages(db, t.id)
    collab_stage = db.query(PipelineStage).filter_by(tenant_id=t.id, key="collaboration_engagement").first()
    guest = _make_guest(db, t.id)
    convo = _make_conversation(db, t.id, guest.id, ChannelType.INSTAGRAM)
    _make_message(db, t.id, convo.id, ChannelType.INSTAGRAM, "hi, interested in a collab / UGC content creator partnership")

    backfill_tenant_leads_from_conversations(db, t.id)

    inquiry = db.query(Inquiry).filter_by(tenant_id=t.id, guest_id=guest.id).first()
    assert inquiry.stage_id == collab_stage.id
    assert inquiry.source == InquirySource.META_IG


def test_backfill_is_idempotent(db):
    t = _make_tenant(db)
    _default_stages(db, t.id)
    guest = _make_guest(db, t.id)
    convo = _make_conversation(db, t.id, guest.id, ChannelType.WHATSAPP)
    _make_message(db, t.id, convo.id, ChannelType.WHATSAPP, "hello")

    first = backfill_tenant_leads_from_conversations(db, t.id)
    second = backfill_tenant_leads_from_conversations(db, t.id)

    assert first["inquiries_created"] == 1
    assert second["inquiries_created"] == 0
    assert db.query(Inquiry).filter_by(tenant_id=t.id, guest_id=guest.id).count() == 1


def test_backfill_skips_guest_with_existing_open_inquiry(db):
    t = _make_tenant(db)
    valid, _ = _default_stages(db, t.id)
    guest = _make_guest(db, t.id)
    existing = Inquiry(
        id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id,
        stage=InquiryStage.NEW, stage_id=valid.id, source=InquirySource.WA_DIRECT,
    )
    db.add(existing)
    convo = _make_conversation(db, t.id, guest.id, ChannelType.WHATSAPP)
    _make_message(db, t.id, convo.id, ChannelType.WHATSAPP, "hello")
    db.flush()

    stats = backfill_tenant_leads_from_conversations(db, t.id)

    assert stats["inquiries_created"] == 0
    assert stats["conversations_linked"] == 1  # still links the conversation to the existing inquiry
    db.refresh(convo)
    assert convo.inquiry_id == existing.id


def test_backfill_skips_guest_with_no_inbound_message(db):
    t = _make_tenant(db)
    _default_stages(db, t.id)
    guest = _make_guest(db, t.id)
    convo = _make_conversation(db, t.id, guest.id, ChannelType.WHATSAPP)
    _make_message(db, t.id, convo.id, ChannelType.WHATSAPP, "outbound only", direction=MessageDirection.OUTBOUND)

    stats = backfill_tenant_leads_from_conversations(db, t.id)

    assert stats["guests_skipped_no_message"] == 1
    assert stats["inquiries_created"] == 0
    assert db.query(Inquiry).filter_by(tenant_id=t.id, guest_id=guest.id).count() == 0


def test_backfill_already_linked_conversation_not_relinked(db):
    t = _make_tenant(db)
    valid, _ = _default_stages(db, t.id)
    guest = _make_guest(db, t.id)
    other_inquiry = Inquiry(
        id=str(uuid.uuid4()), tenant_id=t.id, guest_id=guest.id,
        stage=InquiryStage.NEW, stage_id=valid.id, source=InquirySource.WA_DIRECT,
    )
    db.add(other_inquiry)
    db.flush()
    convo = _make_conversation(db, t.id, guest.id, ChannelType.WHATSAPP, inquiry_id=other_inquiry.id)
    _make_message(db, t.id, convo.id, ChannelType.WHATSAPP, "hello")

    stats = backfill_tenant_leads_from_conversations(db, t.id)

    assert stats["conversations_linked"] == 0  # already had inquiry_id, left untouched
    db.refresh(convo)
    assert convo.inquiry_id == other_inquiry.id


def test_backfill_tenant_isolation(db):
    t1 = _make_tenant(db, "T1")
    t2 = _make_tenant(db, "T2")
    _default_stages(db, t1.id)
    _default_stages(db, t2.id)
    g1 = _make_guest(db, t1.id)
    g2 = _make_guest(db, t2.id)
    c1 = _make_conversation(db, t1.id, g1.id, ChannelType.WHATSAPP)
    c2 = _make_conversation(db, t2.id, g2.id, ChannelType.WHATSAPP)
    _make_message(db, t1.id, c1.id, ChannelType.WHATSAPP, "hi from t1")
    _make_message(db, t2.id, c2.id, ChannelType.WHATSAPP, "hi from t2")

    stats = backfill_tenant_leads_from_conversations(db, t1.id)

    assert stats["guests_processed"] == 1
    assert db.query(Inquiry).filter_by(tenant_id=t1.id).count() == 1
    assert db.query(Inquiry).filter_by(tenant_id=t2.id).count() == 0
