"""Tests for HAIP_AI_Autonomy_Plan.md Phase 2, ticket 5: the send_whatsapp_draft
one-click action -- POST /automations/actions/execute approving + queueing a
pending AI draft, the same action AIRecommendationCard fires from the call
detail page's recommended_actions[].
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Conversation, Message, ChannelType, MessageDeliveryState
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import create_access_token, get_password_hash


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_pending_draft(db, tenant_id, body="Draft reply about the villa."):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone=f"+9199990{uuid.uuid4().hex[:5]}", name="Guest")
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


class TestExecuteSendWhatsappDraft:
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_happy_path_approves_and_queues(self, mock_delay, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv, draft = _make_pending_draft(db, tenant_id)

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "send_whatsapp_draft",
                "entity_refs": {"call_id": str(uuid.uuid4())},
                "action_config": {"message_id": draft.id},
                "source": "call_detail",
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        assert body["action_type"] == "send_whatsapp_draft"

        db.refresh(draft)
        assert draft.was_approved is True
        assert draft.delivery_state == MessageDeliveryState.QUEUED
        mock_delay.assert_called_once_with(message_id=draft.id, tenant_id=tenant_id)

        outcomes = db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).all()
        assert len(outcomes) == 1
        assert outcomes[0].outcome == "sent_verbatim"

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_already_actioned_draft_is_skipped_not_resent(self, mock_delay, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv, draft = _make_pending_draft(db, tenant_id)
        draft.was_approved = True  # already sent once
        db.commit()

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "send_whatsapp_draft",
                "entity_refs": {"call_id": str(uuid.uuid4())},
                "action_config": {"message_id": draft.id},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "already actioned" in resp.json()["detail"]
        mock_delay.assert_not_called()

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_cross_tenant_message_not_touched(self, mock_delay, client, db, tenant_and_user):
        """A message_id belonging to another tenant must not be approved or
        sent, no matter what the caller's own auth token says."""
        other_tenant_id = str(uuid.uuid4())
        db.add(Tenant(id=other_tenant_id, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()
        _, other_draft = _make_pending_draft(db, other_tenant_id)

        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "send_whatsapp_draft",
                "entity_refs": {"call_id": str(uuid.uuid4())},
                "action_config": {"message_id": other_draft.id},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 200
        assert "not found" in resp.json()["detail"]
        mock_delay.assert_not_called()

        db.refresh(other_draft)
        assert other_draft.was_approved is None  # untouched

    def test_unknown_action_type_rejected(self, client, tenant_and_user):
        resp = client.post(
            "/api/v1/automations/actions/execute",
            json={
                "action_type": "delete_everything",
                "entity_refs": {"call_id": str(uuid.uuid4())},
                "action_config": {},
            },
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 422
