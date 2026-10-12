"""Regression tests: approve_ai_draft used to unconditionally dispatch
send_whatsapp.delay() regardless of the conversation's actual channel.
Confirmed live: approving a draft on an Instagram conversation queued a
WhatsApp send against a guest who often has no phone signal at all -- the
UI showed "Draft approved & sent" while the reply silently never reached
the guest. Now routes by the conversation's real channel and fails loudly
for channels with no outbound-send task built yet."""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import Message, MessageDeliveryState, Conversation, ChannelType
from app.models.guest import Guest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # the send routes are gated by conversations.send


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_conversation(db, tenant_id, channel):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Channel Routing Guest")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=channel, is_open=True)
    db.add(conv); db.commit()
    return conv


def _make_draft(db, tenant_id, conversation_id, channel_str):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction="outbound", channel=channel_str, body="Draft reply text",
        is_ai_generated=True, was_approved=None,
    )
    db.add(msg); db.commit()
    return msg


class TestChannelRouting:
    @patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay")
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_instagram_conversation_routes_to_instagram_task_not_whatsapp(
        self, mock_wa_delay, mock_ig_delay, client, db, auth_headers, tenant_and_user,
    ):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id, ChannelType.INSTAGRAM)
        draft = _make_draft(db, tenant_id, conv.id, "instagram")

        res = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{draft.id}/approve",
            json={}, headers=auth_headers,
        )
        assert res.status_code == 200
        mock_ig_delay.assert_called_once_with(message_id=draft.id, tenant_id=tenant_id)
        mock_wa_delay.assert_not_called()

    @patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay")
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_whatsapp_conversation_still_routes_to_whatsapp_task(
        self, mock_wa_delay, mock_ig_delay, client, db, auth_headers, tenant_and_user,
    ):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id, ChannelType.WHATSAPP)
        draft = _make_draft(db, tenant_id, conv.id, "whatsapp")

        res = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{draft.id}/approve",
            json={}, headers=auth_headers,
        )
        assert res.status_code == 200
        mock_wa_delay.assert_called_once_with(message_id=draft.id, tenant_id=tenant_id)
        mock_ig_delay.assert_not_called()

    def test_voice_conversation_rejects_instead_of_misdispatching(self, client, db, auth_headers, tenant_and_user):
        """No outbound-send task exists for voice conversations -- must fail
        loudly (400) rather than silently routing through WhatsApp against
        a guest who may have no phone-based WhatsApp presence at all."""
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id, ChannelType.VOICE)
        draft = _make_draft(db, tenant_id, conv.id, "voice")

        res = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{draft.id}/approve",
            json={}, headers=auth_headers,
        )
        assert res.status_code == 400
        assert "voice" in res.json()["detail"].lower()

        db.refresh(draft)
        assert draft.delivery_state == MessageDeliveryState.FAILED
