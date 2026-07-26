"""
leads_service._batch_pending_drafts() — M5+ WS3 one-click send.
Pending AI draft (is_ai_generated=True, was_approved=None) surfaces on the
lead card; approved/human drafts don't; most-recent wins; tenant-isolated.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.conversation import Conversation, Message, MessageDirection, ChannelType
from app.services.leads_service import _batch_pending_drafts

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _mk_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _mk_inquiry(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone=f"+91{uuid.uuid4().int % 10**10}")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    return inq


def _mk_conversation(db, tenant_id, inquiry, channel=ChannelType.WHATSAPP):
    c = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=inquiry.guest_id,
        inquiry_id=inquiry.id, channel=channel,
    )
    db.add(c)
    db.flush()
    return c


def _mk_draft(db, tenant_id, conv, body="Hi! Yes, the villa is available.",
              is_ai_generated=True, was_approved=None, at=NOW,
              direction=MessageDirection.OUTBOUND):
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction=direction, channel=conv.channel, body=body,
        is_ai_generated=is_ai_generated, was_approved=was_approved,
    )
    db.add(m)
    db.flush()
    m.created_at = at
    db.flush()
    return m


def test_pending_ai_draft_is_returned(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    draft = _mk_draft(db, t.id, conv, body="Yes, the pool villa is available for those dates.")
    db.commit()

    result = _batch_pending_drafts(db, t.id, [inq.id])

    assert inq.id in result
    entry = result[inq.id]
    assert entry.message_id == draft.id
    assert entry.conversation_id == conv.id
    assert entry.preview == "Yes, the pool villa is available for those dates."


def test_approved_draft_excluded(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_draft(db, t.id, conv, was_approved=True)
    db.commit()

    assert inq.id not in _batch_pending_drafts(db, t.id, [inq.id])


def test_human_authored_message_excluded(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_draft(db, t.id, conv, is_ai_generated=False)
    db.commit()

    assert inq.id not in _batch_pending_drafts(db, t.id, [inq.id])


def test_inbound_message_excluded(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_draft(db, t.id, conv, direction=MessageDirection.INBOUND)
    db.commit()

    assert inq.id not in _batch_pending_drafts(db, t.id, [inq.id])


def test_most_recent_draft_wins(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_draft(db, t.id, conv, body="Older draft", at=NOW - timedelta(hours=1))
    newer = _mk_draft(db, t.id, conv, body="Newer draft", at=NOW)
    db.commit()

    entry = _batch_pending_drafts(db, t.id, [inq.id])[inq.id]
    assert entry.message_id == newer.id
    assert entry.preview == "Newer draft"


def test_preview_truncated_to_140_chars(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_draft(db, t.id, conv, body="x" * 200)
    db.commit()

    entry = _batch_pending_drafts(db, t.id, [inq.id])[inq.id]
    assert len(entry.preview) == 140


def test_no_pending_draft_absent_from_result(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    db.commit()
    assert inq.id not in _batch_pending_drafts(db, t.id, [inq.id])


def test_empty_inquiry_ids_returns_empty(db):
    t = _mk_tenant(db)
    assert _batch_pending_drafts(db, t.id, []) == {}


def test_tenant_isolation(db):
    t1 = _mk_tenant(db)
    t2 = _mk_tenant(db)
    inq1 = _mk_inquiry(db, t1.id)
    conv1 = _mk_conversation(db, t1.id, inq1)
    _mk_draft(db, t1.id, conv1)
    db.commit()

    assert _batch_pending_drafts(db, t2.id, [inq1.id]) == {}
    assert inq1.id in _batch_pending_drafts(db, t1.id, [inq1.id])
