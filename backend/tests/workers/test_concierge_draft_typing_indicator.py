"""Guest-visible "typing…" bubble while the concierge draft is generating.
See concierge_draft.py's _send_whatsapp_typing_indicator + meta_cloud.py's
send_typing_indicator.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType
from app.models.integration import Integration
from app.workers.tasks.concierge_draft import concierge_draft


def _setup_conversation(db, channel=ChannelType.WHATSAPP):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500003", name="Anita")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=channel, is_open=True, ai_mode="shadow")
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel=channel.value if hasattr(channel, "value") else channel,
        body="Do you have anything free this weekend?",
        channel_message_id=f"wamid.{uuid.uuid4().hex}",
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class TestTypingIndicator:
    def test_fires_for_whatsapp_conversation_with_integration(self, db, monkeypatch):
        tenant, guest, conv, inbound = _setup_conversation(db, ChannelType.WHATSAPP)
        integration = Integration(
            id=str(uuid.uuid4()), tenant_id=tenant.id, kind="whatsapp_meta", status="active",
            config={"phone_number_id": "123456"},
        )
        db.add(integration); db.commit()

        monkeypatch.setattr("app.workers.tasks.whatsapp._get_wa_access_token", lambda db, tenant_id: "fake-token")

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"reply": "Let me check!", "confidence": 0.5, "citations": [], "needs_human": False}}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        fake_adapter = MagicMock()
        fake_adapter.send_typing_indicator = AsyncMock(return_value={})

        inbound_id, inbound_wamid, conv_id, tenant_id = inbound.id, inbound.channel_message_id, conv.id, tenant.id
        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"), \
             patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=fake_adapter) as mock_get_adapter:
            concierge_draft.run(message_id=inbound_id, conversation_id=conv_id, tenant_id=tenant_id)

        mock_get_adapter.assert_called_once_with("123456", "fake-token")
        # Must send Meta's real WAMID (channel_message_id), never our own
        # internal Message.id -- confirmed live cause of a 400 Bad Request
        # on every typing-indicator call before this fix.
        fake_adapter.send_typing_indicator.assert_awaited_once_with(inbound_wamid)

    def test_no_wamid_does_not_call_adapter(self, db, monkeypatch):
        """A message with no real WAMID on file (channel_message_id unset)
        must not call Meta's API at all -- there's nothing valid to send."""
        tenant, guest, conv, inbound = _setup_conversation(db, ChannelType.WHATSAPP)
        inbound.channel_message_id = None
        db.commit()
        integration = Integration(
            id=str(uuid.uuid4()), tenant_id=tenant.id, kind="whatsapp_meta", status="active",
            config={"phone_number_id": "123456"},
        )
        db.add(integration); db.commit()

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"reply": "Let me check!", "confidence": 0.5, "citations": [], "needs_human": False}}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        fake_adapter = MagicMock()
        fake_adapter.send_typing_indicator = AsyncMock(return_value={})

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"), \
             patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=fake_adapter) as mock_get_adapter:
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        mock_get_adapter.assert_not_called()

    def test_no_integration_does_not_block_draft(self, db, monkeypatch):
        """No WhatsApp integration configured yet -- the typing call quietly
        no-ops, the draft still gets written."""
        tenant, guest, conv, inbound = _setup_conversation(db, ChannelType.WHATSAPP)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"reply": "Let me check!", "confidence": 0.5, "citations": [], "needs_human": False}}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .first()
        )
        assert draft is not None
