"""Regression tests: retry_failed_message used to unconditionally
dispatch send_whatsapp.delay() regardless of the conversation's actual
channel -- same bug class as approve_ai_draft (see
test_approve_draft_channel_routing.py). Confirmed live: a failed Instagram
draft (e.g. approved back when approve_ai_draft still misrouted to
WhatsApp) got retried straight into WhatsApp again and failed again, with
the UI's Retry button never actually able to succeed. Now routes by the
conversation's real channel and fails loudly for channels with no
outbound-send task built yet."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.conversation import Message, MessageDeliveryState, Conversation, ChannelType
from app.models.guest import Guest


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_conversation(db, tenant_id, channel):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Retry Routing Guest")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=channel, is_open=True)
    db.add(conv); db.commit()
    return conv


def _make_failed_message(db, tenant_id, conversation_id, channel_str):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction="outbound", channel=channel_str, body="Reply text",
        is_ai_generated=True, was_approved=True,
        delivery_state=MessageDeliveryState.FAILED, delivery_error="prior failure",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg); db.commit()
    return msg


class TestRetryChannelRouting:
    @patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay")
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_instagram_conversation_retry_routes_to_instagram_task_not_whatsapp(
        self, mock_wa_delay, mock_ig_delay, client, db, auth_headers, tenant_and_user,
    ):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id, ChannelType.INSTAGRAM)
        msg = _make_failed_message(db, tenant_id, conv.id, "instagram")

        res = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{msg.id}/retry",
            headers=auth_headers,
        )
        assert res.status_code == 200
        mock_ig_delay.assert_called_once_with(message_id=msg.id, tenant_id=tenant_id)
        mock_wa_delay.assert_not_called()

    @patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay")
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_whatsapp_conversation_retry_still_routes_to_whatsapp_task(
        self, mock_wa_delay, mock_ig_delay, client, db, auth_headers, tenant_and_user,
    ):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id, ChannelType.WHATSAPP)
        msg = _make_failed_message(db, tenant_id, conv.id, "whatsapp")

        res = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{msg.id}/retry",
            headers=auth_headers,
        )
        assert res.status_code == 200
        mock_wa_delay.assert_called_once_with(message_id=msg.id, tenant_id=tenant_id)
        mock_ig_delay.assert_not_called()

    def test_voice_conversation_retry_rejects_instead_of_misdispatching(
        self, client, db, auth_headers, tenant_and_user,
    ):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id, ChannelType.VOICE)
        msg = _make_failed_message(db, tenant_id, conv.id, "voice")

        res = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{msg.id}/retry",
            headers=auth_headers,
        )
        assert res.status_code == 400
        assert "voice" in res.json()["detail"].lower()

        db.refresh(msg)
        assert msg.delivery_state == MessageDeliveryState.FAILED
