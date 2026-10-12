"""
Tests for B4: Idempotency keys on outbound sends.

Covers:
- Duplicate send with same key returns original message (no duplicate created)
- Different key creates a new message
- Absent header → no dedup, normal message created
- Key >64 chars → 400 validation error
- Expired key (>24h old) treated as new → new message created
- Helper: _extract_idempotency_key strips whitespace, reads both cases
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.v1.endpoints.conversations import (
    _extract_idempotency_key,
    _find_idempotent_message,
    _IDEMPOTENCY_KEY_MAX_LEN,
    _IDEMPOTENCY_WINDOW_HOURS,
)

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # the send routes are gated by conversations.send


# ─────────────────────────────────────────────────────────────────
# Unit tests: _extract_idempotency_key
# ─────────────────────────────────────────────────────────────────

def _make_request(headers: dict) -> Request:
    """Build a minimal Starlette Request with the given headers."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }
    return Request(scope)


class TestExtractIdempotencyKey:
    def test_absent_header_returns_none(self):
        req = _make_request({})
        assert _extract_idempotency_key(req) is None

    def test_present_header_returned(self):
        key = str(uuid.uuid4())
        req = _make_request({"Idempotency-Key": key})
        assert _extract_idempotency_key(req) == key

    def test_lowercase_header_name_accepted(self):
        key = str(uuid.uuid4())
        req = _make_request({"idempotency-key": key})
        assert _extract_idempotency_key(req) == key

    def test_whitespace_stripped(self):
        key = str(uuid.uuid4())
        req = _make_request({"Idempotency-Key": f"  {key}  "})
        assert _extract_idempotency_key(req) == key

    def test_empty_header_returns_none(self):
        req = _make_request({"Idempotency-Key": "   "})
        assert _extract_idempotency_key(req) is None

    def test_key_at_max_length_accepted(self):
        key = "a" * _IDEMPOTENCY_KEY_MAX_LEN
        req = _make_request({"Idempotency-Key": key})
        assert _extract_idempotency_key(req) == key

    def test_key_over_max_length_raises_400(self):
        from fastapi import HTTPException
        key = "a" * (_IDEMPOTENCY_KEY_MAX_LEN + 1)
        req = _make_request({"Idempotency-Key": key})
        with pytest.raises(HTTPException) as exc_info:
            _extract_idempotency_key(req)
        assert exc_info.value.status_code == 400
        assert str(_IDEMPOTENCY_KEY_MAX_LEN) in exc_info.value.detail


# ─────────────────────────────────────────────────────────────────
# Unit tests: _find_idempotent_message
# ─────────────────────────────────────────────────────────────────

def _make_message(tenant_id: str, key: str, created_at: str):
    msg = MagicMock()
    msg.tenant_id = tenant_id
    msg.idempotency_key = key
    msg.created_at = created_at
    return msg


class TestFindIdempotentMessage:
    def test_returns_matching_message_within_window(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        msg = _make_message("t1", "key-abc", recent)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = msg

        result = _find_idempotent_message(db, "t1", "key-abc")
        assert result is msg

    def test_returns_none_when_no_match(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = _find_idempotent_message(db, "t1", "key-notexist")
        assert result is None


# ─────────────────────────────────────────────────────────────────
# Integration tests via TestClient
# ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def conversation(db, tenant_and_user):
    """Create a minimal Conversation row for testing."""
    import uuid as _uuid
    from app.models.conversation import Conversation
    from app.models.guest import Guest

    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id

    guest = Guest(
        id=str(_uuid.uuid4()),
        tenant_id=tenant_id,
        phone="+919999000001",
        name="Idem Test Guest",
    )
    db.add(guest)
    db.flush()

    conv = Conversation(
        id=str(_uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest.id,
        channel="whatsapp",
        is_open=True,
    )
    db.add(conv)
    db.commit()
    return conv


class TestSendMessageIdempotency:
    """End-to-end tests through the POST /conversations/{id}/messages endpoint."""

    def _post(self, client, conv_id, body="Hello", extra_headers=None):
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        return client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"body": body},
            headers=headers,
        )

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_absent_key_creates_message(self, mock_delay, client, auth_headers, conversation):
        client.headers.update(auth_headers)
        resp = self._post(client, conversation.id)
        assert resp.status_code == 201
        data = resp.json()
        assert data["body"] == "Hello"
        assert data["idempotency_key"] is None
        mock_delay.assert_called_once()

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_same_key_returns_original_no_duplicate(self, mock_delay, client, auth_headers, conversation):
        """Two sends with the same Idempotency-Key return the same message. Worker called once."""
        client.headers.update(auth_headers)
        key = str(uuid.uuid4())

        resp1 = self._post(client, conversation.id, extra_headers={"Idempotency-Key": key})
        assert resp1.status_code == 201
        msg_id = resp1.json()["id"]

        resp2 = self._post(client, conversation.id, extra_headers={"Idempotency-Key": key})
        # Second call returns the original (200 or 201 — status_code not guaranteed equal)
        assert resp2.json()["id"] == msg_id

        # Worker should only have been called once (dedup hit on second request)
        mock_delay.assert_called_once()

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_different_key_creates_new_message(self, mock_delay, client, auth_headers, conversation):
        """Two sends with different keys → two distinct messages."""
        client.headers.update(auth_headers)

        resp1 = self._post(client, conversation.id, extra_headers={"Idempotency-Key": str(uuid.uuid4())})
        resp2 = self._post(client, conversation.id, extra_headers={"Idempotency-Key": str(uuid.uuid4())})

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] != resp2.json()["id"]
        assert mock_delay.call_count == 2

    def test_key_too_long_returns_400(self, client, auth_headers, conversation):
        client.headers.update(auth_headers)
        long_key = "x" * 65
        resp = self._post(client, conversation.id, extra_headers={"Idempotency-Key": long_key})
        assert resp.status_code == 400
        assert "64" in resp.json()["detail"]

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_expired_key_creates_new_message(self, mock_delay, client, auth_headers, conversation, db):
        """A message with the same key but created >24h ago should not block a new send."""
        import uuid as _uuid
        from app.models.conversation import Message

        tenant_id = conversation.tenant_id
        stale_key = str(_uuid.uuid4())
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=_IDEMPOTENCY_WINDOW_HOURS + 1)).isoformat()

        # Insert an old message with the key directly — bypassing the API
        old_msg = Message(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            direction="outbound",
            channel="whatsapp",
            body="Old message",
            idempotency_key=stale_key,
            was_approved=True,
        )
        db.add(old_msg)
        # Manually set created_at to past (TimestampMixin uses server_default, override here)
        db.flush()
        db.execute(
            __import__("sqlalchemy").text("UPDATE messages SET created_at = :ts WHERE id = :id"),
            {"ts": old_ts, "id": old_msg.id},
        )
        db.commit()

        client.headers.update(auth_headers)
        resp = self._post(client, conversation.id, extra_headers={"Idempotency-Key": stale_key})
        assert resp.status_code == 201
        # Should be a NEW message, not the old one
        assert resp.json()["id"] != old_msg.id
        mock_delay.assert_called_once()

        # Regression (Phase 0.1): uq_messages_idempotency covers all time, so the expired key had to be released
        # from the old message; before, PostgreSQL rejected the new insert with a unique violation (HTTP 500).
        db.expire_all()
        holders = db.query(Message).filter(Message.tenant_id == tenant_id, Message.idempotency_key == stale_key).all()
        assert [m.id for m in holders] == [resp.json()["id"]]
        assert db.get(Message, old_msg.id).body == "Old message"       # the old message itself is untouched
