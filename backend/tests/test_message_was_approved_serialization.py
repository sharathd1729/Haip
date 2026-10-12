"""Regression: the message serializer (_msg_dict, shared by GET
/conversations/{id} and GET /conversations/{id}/messages) never included
was_approved in the response at all -- even though approve_ai_draft/
reject_ai_draft correctly set it on the DB row. The frontend had no way to
tell an already-approved draft from a still-pending one, so the
Approve/Edit/Reject card kept showing on a message that had already been
sent to the guest."""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import Message, Conversation, ChannelType
from app.models.guest import Guest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # the send routes are gated by conversations.send


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_conversation(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Was Approved Guest")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


def _make_draft(db, tenant_id, conversation_id):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation_id,
        direction="outbound", channel="whatsapp", body="Draft reply text",
        is_ai_generated=True, was_approved=None,
    )
    db.add(msg); db.commit()
    return msg


def _find_message(payload: dict, message_id: str) -> dict:
    return next(m for m in payload["messages"] if m["id"] == message_id)


def test_pending_draft_serializes_was_approved_null(client, db, auth_headers, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    conv = _make_conversation(db, tenant_id)
    draft = _make_draft(db, tenant_id, conv.id)

    res = client.get(f"/api/v1/conversations/{conv.id}", headers=auth_headers)
    assert res.status_code == 200
    msg = _find_message(res.json(), draft.id)
    assert msg["was_approved"] is None
    assert msg["ai_drafted"] is True


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_approved_draft_serializes_was_approved_true(mock_delay, client, db, auth_headers, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    conv = _make_conversation(db, tenant_id)
    draft = _make_draft(db, tenant_id, conv.id)

    approve_res = client.post(
        f"/api/v1/conversations/{conv.id}/messages/{draft.id}/approve",
        json={}, headers=auth_headers,
    )
    assert approve_res.status_code == 200

    res = client.get(f"/api/v1/conversations/{conv.id}", headers=auth_headers)
    assert res.status_code == 200
    msg = _find_message(res.json(), draft.id)
    assert msg["was_approved"] is True


def test_rejected_draft_serializes_was_approved_false(client, db, auth_headers, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    conv = _make_conversation(db, tenant_id)
    draft = _make_draft(db, tenant_id, conv.id)

    reject_res = client.post(
        f"/api/v1/conversations/{conv.id}/messages/{draft.id}/reject",
        headers=auth_headers,
    )
    assert reject_res.status_code == 200

    res = client.get(f"/api/v1/conversations/{conv.id}", headers=auth_headers)
    assert res.status_code == 200
    msg = _find_message(res.json(), draft.id)
    assert msg["was_approved"] is False
