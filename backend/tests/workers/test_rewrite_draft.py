"""Tests for HAIP Inbox prototype-wiring plan, ticket 3: real translate +
real tone-fix (rewrite_draft Celery task + its endpoint)."""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.workers.tasks.rewrite_draft import rewrite_draft, _build_system_prompt


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_pending_draft(db, tenant_id, body="Hey, the villa is free those dates!"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone=f"+9199990{uuid.uuid4().hex[:5]}")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction="outbound", channel="whatsapp", body=body,
        is_ai_generated=True, was_approved=None,
    )
    db.add(msg); db.commit()
    return conv, msg


class TestBuildSystemPrompt:
    def test_tone_instruction_included(self):
        prompt = _build_system_prompt("Hello", tone="brief", target_language=None)
        assert "brief" in prompt.lower()

    def test_translate_instruction_included(self):
        prompt = _build_system_prompt("Hello", tone=None, target_language="Hindi")
        assert "Hindi" in prompt

    def test_preserves_facts_instruction_always_present(self):
        prompt = _build_system_prompt("Total is ₹5000", tone="warm", target_language=None)
        assert "Never change" in prompt


class TestRewriteDraftTask:
    def test_rewrites_pending_draft_in_place(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv, msg = _make_pending_draft(db, tenant_id)
        msg_id = msg.id

        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"rewritten_text": "Hi! Great news, the villa is available on those dates."}}

        with patch("app.workers.tasks.rewrite_draft.get_llm", return_value=_FakeLLM()), \
             patch("app.workers.tasks.rewrite_draft.SessionLocal", return_value=db):
            rewrite_draft.run(message_id=msg_id, tenant_id=tenant_id, tone="warm")

        reloaded = db.query(Message).filter_by(id=msg_id).first()
        assert reloaded.body == "Hi! Great news, the villa is available on those dates."

    def test_skips_already_approved_message(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv, msg = _make_pending_draft(db, tenant_id)
        msg.was_approved = True
        db.commit()
        msg_id = msg.id
        original_body = msg.body

        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"rewritten_text": "Should never see this"}}

        with patch("app.workers.tasks.rewrite_draft.get_llm", return_value=_FakeLLM()), \
             patch("app.workers.tasks.rewrite_draft.SessionLocal", return_value=db):
            rewrite_draft.run(message_id=msg_id, tenant_id=tenant_id, tone="warm")

        reloaded = db.query(Message).filter_by(id=msg_id).first()
        assert reloaded.body == original_body


@pytest.mark.usefixtures("capabilities_seeded")   # the POST is gated by conversations.send
class TestRewriteDraftEndpoint:
    @patch("app.workers.tasks.rewrite_draft.rewrite_draft.delay")
    def test_happy_path_queues_task(self, mock_delay, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv, msg = _make_pending_draft(db, tenant_id)

        resp = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{msg.id}/rewrite",
            json={"tone": "brief"},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rewrite_queued"
        mock_delay.assert_called_once_with(message_id=msg.id, tenant_id=tenant_id, tone="brief", target_language=None)

    @patch("app.workers.tasks.rewrite_draft.rewrite_draft.delay")
    def test_already_approved_message_rejected(self, mock_delay, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv, msg = _make_pending_draft(db, tenant_id)
        msg.was_approved = True
        db.commit()

        resp = client.post(
            f"/api/v1/conversations/{conv.id}/messages/{msg.id}/rewrite",
            json={"tone": "brief"},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 409
        mock_delay.assert_not_called()

    def test_unknown_message_404(self, client, tenant_and_user):
        resp = client.post(
            f"/api/v1/conversations/{uuid.uuid4()}/messages/{uuid.uuid4()}/rewrite",
            json={"tone": "brief"},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 404
