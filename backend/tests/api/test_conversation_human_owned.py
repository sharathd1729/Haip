"""Auto-shadow on handoff: the first time a human agent sends, template-
sends, or approves an outbound message in a conversation, Conversation.
human_owned flips True -- ai_mode_service.resolve_mode() then forces
shadow mode regardless of the tenant's autonomous default, so the bot
never auto-sends into a thread a person is actively working. An internal
note (never seen by the guest) must not count as taking over.
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import Conversation, Message, ChannelType, MessageDeliveryState
from app.models.guest import Guest
from app.api.v1.endpoints.messaging import WATemplate, TemplateStatus


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


@pytest.fixture()
def conversation(db, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="+919999000004")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


class TestManualSend:
    def test_sending_a_reply_sets_human_owned(self, client, db, tenant_and_user, conversation):
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "Sure, let me check availability for you."},
            headers=headers,
        )
        assert resp.status_code == 201
        db.refresh(conversation)
        assert conversation.human_owned is True

    def test_internal_note_does_not_set_human_owned(self, client, db, tenant_and_user, conversation):
        """An internal note is never seen by the guest -- it isn't taking
        over the conversation."""
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "Reminder: call back after lunch", "is_internal": True},
            headers=headers,
        )
        assert resp.status_code == 201
        db.refresh(conversation)
        assert conversation.human_owned is False


class TestTemplateSend:
    def test_sending_a_template_sets_human_owned(self, client, db, tenant_and_user, conversation):
        tenant_id = _tenant_id(tenant_and_user)
        tmpl = WATemplate(
            id=str(uuid.uuid4()), tenant_id=tenant_id, name="booking_confirmation", language="en",
            status=TemplateStatus.APPROVED,
            components=[{"type": "BODY", "text": "Hi {{1}}, your stay is confirmed."}],
        )
        db.add(tmpl); db.commit()
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay"):
            resp = client.post(
                f"/api/v1/conversations/{conversation.id}/send-template",
                json={"template_id": tmpl.id, "variables": ["Priya"]},
                headers=headers,
            )
        assert resp.status_code == 201
        db.refresh(conversation)
        assert conversation.human_owned is True


class TestApproveDraft:
    def test_approving_a_draft_sets_human_owned(self, client, db, tenant_and_user, conversation):
        tenant_id = _tenant_id(tenant_and_user)
        msg = Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation.id,
            direction="outbound", channel=ChannelType.WHATSAPP, body="Draft reply text",
            is_ai_generated=True, was_approved=None,
        )
        db.add(msg); db.commit()
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
            resp = client.post(
                f"/api/v1/conversations/{conversation.id}/messages/{msg.id}/approve",
                headers=headers,
            )
        assert resp.status_code == 200
        db.refresh(conversation)
        assert conversation.human_owned is True
