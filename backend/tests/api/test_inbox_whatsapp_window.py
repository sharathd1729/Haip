"""The inbox refuses free text to a WhatsApp guest outside the 24-hour window (conversations.send_message).

Meta rejects those sends after they look sent; HAIP now says so up front and points to a template. Internal notes and
other channels are unaffected.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _conv(db, tenant_and_user, channel=ChannelType.WHATSAPP, last_inbound_minutes=None):
    t = tenant_and_user["tenant"]
    tid = t["id"] if isinstance(t, dict) else t.id
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Ananya", phone="+919886140372")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, is_open=True)
    db.add(c)
    db.flush()
    if last_inbound_minutes is not None:
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction="inbound", channel=channel,
                       body="Hi", created_at=datetime.now(timezone.utc) - timedelta(minutes=last_inbound_minutes)))
    db.commit()
    return c


def _send(client, tenant_and_user, conv, **body):
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"), \
            patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay"):
        return client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Hello", **body},
                           headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})


@pytest.mark.parametrize("minutes,status", [(None, 409), (25 * 60, 409), (60, 201)])
def test_free_text_needs_the_guest_to_have_written_in_the_last_24_hours(client, db, tenant_and_user, minutes, status):
    conv = _conv(db, tenant_and_user, last_inbound_minutes=minutes)
    res = _send(client, tenant_and_user, conv)
    assert res.status_code == status, res.text
    if status == 409:
        assert "template" in res.json()["detail"]
        assert db.query(Message).filter_by(conversation_id=conv.id, direction="outbound").count() == 0


def test_an_internal_note_is_always_allowed(client, db, tenant_and_user):
    conv = _conv(db, tenant_and_user)
    assert _send(client, tenant_and_user, conv, is_internal=True).status_code == 201


def test_instagram_is_not_affected(client, db, tenant_and_user):
    conv = _conv(db, tenant_and_user, channel=ChannelType.INSTAGRAM)
    assert _send(client, tenant_and_user, conv).status_code == 201
