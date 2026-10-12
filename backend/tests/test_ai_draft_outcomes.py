"""Tests for HAIP_AI_Autonomy_Plan.md Phase 0, ticket 1:

- approve_ai_draft now honors edited text instead of silently sending the
  original AI draft regardless of what the agent typed (the bug).
- reject_ai_draft now exists at all (it 404'd before, silently swallowed
  by the frontend).
- Both write an ai_draft_outcomes row capturing the training signal.
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import Message, MessageDeliveryState, Conversation, ChannelType
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.guest import Guest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # the send routes are gated by conversations.send


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def conversation(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone="+919999000003", name="Outcome Test Guest")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


def _make_draft(db, tenant_id, conversation_id, body="Original AI draft text about the villa."):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction="outbound", channel="whatsapp", body=body,
        is_ai_generated=True, was_approved=None, ai_confidence="0.82",
    )
    db.add(msg); db.commit()
    return msg


class TestApproveVerbatim:
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_approve_no_body_sends_verbatim(self, mock_delay, client, db, auth_headers, conversation, tenant_and_user):
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        draft = _make_draft(db, tenant_id, conversation.id)

        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages/{draft.id}/approve",
            json={}, headers=auth_headers,
        )
        assert resp.status_code == 200

        db.refresh(draft)
        assert draft.was_approved is True
        assert draft.body == "Original AI draft text about the villa."  # unchanged
        assert draft.delivery_state == MessageDeliveryState.QUEUED

        outcomes = db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).all()
        assert len(outcomes) == 1
        assert outcomes[0].outcome == "sent_verbatim"
        assert outcomes[0].edit_distance_pct is None
        assert outcomes[0].ai_confidence == "0.82"
        assert outcomes[0].time_to_action_sec is not None
        # Phase 2.5 (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.4)
        actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
        assert outcomes[0].actor_user_id == actor_id


class TestApproveEdited:
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_approve_with_edited_text_actually_sends_the_edit(self, mock_delay, client, db, auth_headers, conversation, tenant_and_user):
        """The bug: this used to silently ignore body.text and always send
        the original draft. The guest would receive the AI's unedited text
        even after an agent visibly corrected it in the UI."""
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        draft = _make_draft(db, tenant_id, conversation.id, body="The villa is available on the 14th for ₹40,000.")

        edited = "Sorry, that villa is actually booked on the 14th -- I can offer the 16th instead."
        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages/{draft.id}/approve",
            json={"text": edited}, headers=auth_headers,
        )
        assert resp.status_code == 200

        db.refresh(draft)
        assert draft.body == edited  # the edit actually took effect
        assert draft.was_approved is True

        outcomes = db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).all()
        assert len(outcomes) == 1
        assert outcomes[0].outcome == "sent_edited"
        assert outcomes[0].edit_distance_pct is not None
        assert 0 < outcomes[0].edit_distance_pct < 100  # similar but not identical

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_approve_with_identical_text_is_still_verbatim(self, mock_delay, client, db, auth_headers, conversation, tenant_and_user):
        """Sending {text: <same as draft>} shouldn't be misclassified as an edit."""
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        draft = _make_draft(db, tenant_id, conversation.id, body="Same text either way.")

        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages/{draft.id}/approve",
            json={"text": "Same text either way."}, headers=auth_headers,
        )
        assert resp.status_code == 200

        outcomes = db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).all()
        assert outcomes[0].outcome == "sent_verbatim"
        assert outcomes[0].edit_distance_pct is None


class TestReject:
    def test_reject_endpoint_exists_and_records_outcome(self, client, db, auth_headers, conversation, tenant_and_user):
        """Previously 404'd -- the frontend's reject button has always
        called this exact path and always silently failed."""
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        draft = _make_draft(db, tenant_id, conversation.id)

        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages/{draft.id}/reject",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        db.refresh(draft)
        assert draft.was_approved is False

        outcomes = db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).all()
        assert len(outcomes) == 1
        assert outcomes[0].outcome == "rejected"
        assert outcomes[0].edit_distance_pct is None
        # Phase 2.5 (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.4) --
        # previously reject_ai_draft captured no actor at all.
        actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
        assert outcomes[0].actor_user_id == actor_id


class TestTenantIsolation:
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_cannot_approve_another_tenants_draft(self, mock_delay, client, db, auth_headers, tenant_and_user):
        from app.models.tenant import Tenant
        other_tenant = Tenant(id=str(uuid.uuid4()), name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other_tenant); db.flush()
        other_guest = Guest(id=str(uuid.uuid4()), tenant_id=other_tenant.id, phone="+910000000088", name="Other Guest")
        db.add(other_guest); db.flush()
        other_conv = Conversation(id=str(uuid.uuid4()), tenant_id=other_tenant.id, guest_id=other_guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(other_conv); db.commit()

        other_draft = _make_draft(db, other_tenant.id, other_conv.id)

        resp = client.post(
            f"/api/v1/conversations/{other_conv.id}/messages/{other_draft.id}/approve",
            json={}, headers=auth_headers,
        )
        assert resp.status_code == 404

        db.refresh(other_draft)
        assert other_draft.was_approved is None  # untouched
        assert db.query(AIDraftOutcome).filter_by(draft_message_id=other_draft.id).count() == 0
