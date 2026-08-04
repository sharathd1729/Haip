"""Tests for HAIP Inbox UI-fidelity pass, ticket 3: concierge_draft's
grounded loop only ever proposed a one-click card for price_quote intent
(send_quote) -- the AI card was too narrowly triggered to ever be seen in
practice. This widens it: when the guest has no phone signal on file, the
draft's suggested_actions carries a send_whatsapp_draft entry pointing at
itself (reusing the existing action, not a new one)."""
import uuid
from unittest.mock import MagicMock, patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.conversation import Conversation, Message, ChannelType
from app.workers.tasks.concierge_draft import concierge_draft


def _setup_conversation(db, with_phone_signal: bool):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone=None, name="Priya")
    db.add(guest); db.commit()
    if with_phone_signal:
        db.add(GuestIdentity(
            id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
            identity_type=IdentityType.PHONE.value, identity_value="+919876500001", confidence=0.90,
        ))
        db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True, ai_mode="shadow")
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="whatsapp", body="Hi, do you have a villa for next weekend?",
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _FakeIntentLLM:
    async def complete(self, **kwargs):
        return {"tool_use": {"intent": "general"}}


def _confident_reply_llm(needs_human=False, reply="Sure, let me know your dates and I'll check for you!"):
    class _Fake:
        async def complete(self, **kwargs):
            return {"tool_use": {"reply": reply, "confidence": 0.9, "citations": [], "needs_human": needs_human}}
    return _Fake()


def _run_draft(db, conv, inbound, tenant, reply_llm):
    def _fake_get_llm(task):
        return _FakeIntentLLM() if task == "quick_classify" else reply_llm
    with patch("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

    return (
        db.query(Message)
        .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
        .order_by(Message.created_at.desc())
        .first()
    )


class TestPhoneNudgeSuggestedAction:
    def test_missing_phone_adds_send_whatsapp_draft_action(self, db):
        tenant, guest, conv, inbound = _setup_conversation(db, with_phone_signal=False)
        draft = _run_draft(db, conv, inbound, tenant, _confident_reply_llm())

        assert draft is not None
        actions = draft.suggested_actions or []
        nudge = next((a for a in actions if a["action_type"] == "send_whatsapp_draft"), None)
        assert nudge is not None
        assert nudge["action_config"]["message_id"] == draft.id
        assert nudge["action_config"]["conversation_id"] == conv.id
        assert nudge["confirm"] is True

    def test_guest_with_phone_signal_gets_no_nudge(self, db):
        tenant, guest, conv, inbound = _setup_conversation(db, with_phone_signal=True)
        draft = _run_draft(db, conv, inbound, tenant, _confident_reply_llm())

        assert draft is not None
        actions = draft.suggested_actions or []
        assert not any(a["action_type"] == "send_whatsapp_draft" for a in actions)

    def test_needs_human_draft_gets_no_nudge(self, db):
        """Don't offer a one-click 'send' card for a draft that needs human
        review anyway -- that would misrepresent it as safe to auto-send."""
        tenant, guest, conv, inbound = _setup_conversation(db, with_phone_signal=False)
        draft = _run_draft(db, conv, inbound, tenant, _confident_reply_llm(needs_human=True))

        assert draft is not None
        actions = draft.suggested_actions or []
        assert not any(a["action_type"] == "send_whatsapp_draft" for a in actions)

    def test_autonomous_auto_send_gets_no_nudge(self, db):
        """Already being sent automatically -- a 'send it' card would be
        redundant/confusing."""
        tenant, guest, conv, inbound = _setup_conversation(db, with_phone_signal=False)
        conv.ai_mode = "autonomous"
        db.commit()

        with patch("app.workers.tasks.concierge_draft.get_llm",
                   lambda task: _FakeIntentLLM() if task == "quick_classify" else _confident_reply_llm()), \
             patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"), \
             patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .order_by(Message.created_at.desc())
            .first()
        )
        assert draft is not None
        assert draft.was_approved is True  # auto-sent
        actions = draft.suggested_actions or []
        assert not any(a["action_type"] == "send_whatsapp_draft" for a in actions)
