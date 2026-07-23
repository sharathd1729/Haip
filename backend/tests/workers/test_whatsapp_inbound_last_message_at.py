"""
Regression test: WhatsApp inbound messages must set
Conversation.last_message_at, same as Instagram's inbound handlers already
do (process_instagram_dm.py, process_instagram_comment.py).

Found live in prod: a guest's WhatsApp message never updates this field,
so the conversation's sort key stays NULL until an agent replies. NULL
sorts last (nullslast()), so any unanswered WhatsApp conversation gets
pushed off the inbox's default 50-item fetch by Instagram's higher
volume -- effectively invisible to the team until someone happens to
find and reply to it first.
"""
import uuid

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, ChannelType
from app.workers.tasks.whatsapp import _handle_inbound_message


def _mk_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _wa_message(msg_id="wamid.test1", from_number="919876543210"):
    return {
        "id": msg_id,
        "from": from_number,
        "type": "text",
        "text": {"body": "Hi"},
    }


def test_inbound_text_message_sets_last_message_at(db):
    tenant = _mk_tenant(db)
    db.commit()

    _handle_inbound_message(db, tenant, _wa_message(), contacts=[])
    db.commit()

    conv = db.query(Conversation).filter_by(tenant_id=tenant.id, channel=ChannelType.WHATSAPP).first()
    assert conv is not None
    assert conv.last_message_at is not None


def test_second_inbound_message_bumps_last_message_at(db):
    """A guest's second message (same open conversation) must also refresh
    the sort key, not just the first."""
    tenant = _mk_tenant(db)
    db.commit()

    _handle_inbound_message(db, tenant, _wa_message(msg_id="wamid.a"), contacts=[])
    db.commit()
    conv = db.query(Conversation).filter_by(tenant_id=tenant.id, channel=ChannelType.WHATSAPP).first()
    first_ts = conv.last_message_at
    assert first_ts is not None

    _handle_inbound_message(db, tenant, _wa_message(msg_id="wamid.b"), contacts=[])
    db.commit()
    db.refresh(conv)
    assert conv.last_message_at is not None
    assert conv.last_message_at >= first_ts
