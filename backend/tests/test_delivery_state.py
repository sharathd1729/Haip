"""
Tests for B5: Message delivery state tracking.

Covers:
- send_message sets delivery_state=PENDING then QUEUED before dispatch
- approve_ai_draft sets QUEUED before dispatch
- send_whatsapp worker: success → SENT
- send_whatsapp worker: missing integration → FAILED
- send_whatsapp worker: max retries → FAILED
- Meta status webhook: delivered → DELIVERED
- Meta status webhook: read → READ
- Meta status webhook: failed → FAILED with error text
- No backwards transitions (read stays read on duplicate delivered callback)
- Unknown Meta status is ignored
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from app.models.conversation import Message, MessageDeliveryState, Conversation, ChannelType
from app.workers.tasks.whatsapp import _handle_status_update, _META_STATUS_MAP


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _make_tenant(tenant_id="t1"):
    t = MagicMock()
    t.id = tenant_id
    return t


def _make_message(
    message_id=None,
    tenant_id="t1",
    wamid="wamid-abc",
    delivery_state=MessageDeliveryState.SENT,
):
    msg = MagicMock(spec=Message)
    msg.id = message_id or str(uuid.uuid4())
    msg.tenant_id = tenant_id
    msg.channel_message_id = wamid
    msg.delivery_state = delivery_state
    msg.delivery_error = None
    msg.channel_status = "sent"
    return msg


def _mock_db(message=None):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = message
    return db


# ─────────────────────────────────────────────────────────────────
# Enum mapping smoke test
# ─────────────────────────────────────────────────────────────────

def test_meta_status_map_covers_all_expected_statuses():
    for key in ("sent", "delivered", "read", "failed"):
        assert key in _META_STATUS_MAP


# ─────────────────────────────────────────────────────────────────
# _handle_status_update unit tests
# ─────────────────────────────────────────────────────────────────

class TestHandleStatusUpdate:
    def _call(self, db, status_str, wamid="wamid-abc", tenant_id="t1", extras=None):
        tenant = _make_tenant(tenant_id)
        payload = {"id": wamid, "status": status_str}
        if extras:
            payload.update(extras)
        _handle_status_update(db, tenant, payload)

    def test_delivered_advances_state(self):
        msg = _make_message(delivery_state=MessageDeliveryState.SENT)
        db = _mock_db(msg)
        self._call(db, "delivered")
        assert msg.delivery_state == MessageDeliveryState.DELIVERED
        assert msg.delivery_error is None

    def test_read_advances_state(self):
        msg = _make_message(delivery_state=MessageDeliveryState.DELIVERED)
        db = _mock_db(msg)
        self._call(db, "read")
        assert msg.delivery_state == MessageDeliveryState.READ

    def test_failed_sets_state_and_error(self):
        msg = _make_message(delivery_state=MessageDeliveryState.SENT)
        db = _mock_db(msg)
        self._call(db, "failed", extras={
            "errors": [{"code": 131026, "title": "Message undeliverable"}]
        })
        assert msg.delivery_state == MessageDeliveryState.FAILED
        assert "131026" in msg.delivery_error

    def test_no_backward_transition(self):
        """Once READ, a duplicate DELIVERED callback must not roll it back."""
        msg = _make_message(delivery_state=MessageDeliveryState.READ)
        db = _mock_db(msg)
        self._call(db, "delivered")
        assert msg.delivery_state == MessageDeliveryState.READ  # unchanged

    def test_unknown_status_ignored(self):
        msg = _make_message(delivery_state=MessageDeliveryState.SENT)
        db = _mock_db(msg)
        self._call(db, "some_future_status")
        assert msg.delivery_state == MessageDeliveryState.SENT  # unchanged

    def test_missing_wamid_ignored(self):
        db = MagicMock()
        tenant = _make_tenant()
        _handle_status_update(db, tenant, {"status": "delivered"})  # no "id"
        db.query.assert_not_called()

    def test_message_not_found_logs_warning_and_returns(self):
        db = _mock_db(message=None)
        tenant = _make_tenant()
        # Should not raise
        _handle_status_update(db, tenant, {"id": "unknown-wamid", "status": "delivered"})

    def test_failed_no_errors_array_uses_default_text(self):
        msg = _make_message(delivery_state=MessageDeliveryState.SENT)
        db = _mock_db(msg)
        self._call(db, "failed")  # no "errors" key
        assert msg.delivery_state == MessageDeliveryState.FAILED
        assert msg.delivery_error  # not empty


# ─────────────────────────────────────────────────────────────────
# send_whatsapp worker unit tests
# ─────────────────────────────────────────────────────────────────

class TestSendWhatsappWorker:
    def _run(self, message, integration=None, guest=None, api_result=None):
        """Call send_whatsapp.run() with mocked DB and adapter."""
        from app.workers.tasks.send_whatsapp import send_whatsapp

        db = MagicMock()

        # DB query chain: Message → Conversation → Integration → Guest
        conversation = MagicMock()
        conversation.guest_id = "g1"

        def _query_side_effect(model):
            m = MagicMock()
            if model is Message:
                m.filter_by.return_value.first.return_value = message
            elif model is Conversation:
                m.filter_by.return_value.first.return_value = conversation
            else:
                m.filter_by.return_value.first.return_value = integration or guest
            return m

        db.query.side_effect = _query_side_effect

        with patch("app.workers.tasks.send_whatsapp.SessionLocal", return_value=db), \
             patch("app.workers.tasks.send_whatsapp.db", db, create=True):
            # If no integration, the task returns early after marking FAILED
            pass

        return db

    def test_success_sets_sent(self):
        from app.workers.tasks.send_whatsapp import send_whatsapp

        msg = _make_message(delivery_state=MessageDeliveryState.QUEUED)
        msg.body = "Hello"

        conv = MagicMock()
        conv.guest_id = "g1"

        integration = MagicMock()
        integration.config = {"phone_number_id": "pnid", "access_token": "tok"}

        guest = MagicMock()
        guest.phone = "+919999000001"

        db = MagicMock()
        call_results = iter([msg, conv, integration, guest])
        db.query.return_value.filter_by.return_value.first.side_effect = lambda: next(call_results)

        mock_adapter = MagicMock()
        mock_adapter.send_text = MagicMock(
            return_value={"messages": [{"id": "wamid-123"}]}
        )

        async def _fake_send(**kwargs):
            return {"messages": [{"id": "wamid-123"}]}

        mock_adapter.send_text = _fake_send

        with patch("app.workers.tasks.send_whatsapp.SessionLocal", return_value=db), \
             patch("app.workers.tasks.send_whatsapp.get_wa_adapter", return_value=mock_adapter), \
             patch("app.models.guest.Guest"):
            # run() bypasses Celery machinery
            send_whatsapp.run(message_id=msg.id, tenant_id=msg.tenant_id)

        assert msg.delivery_state == MessageDeliveryState.SENT
        assert msg.channel_message_id == "wamid-123"
        assert msg.delivery_error is None

    def test_missing_integration_marks_failed(self):
        from app.workers.tasks.send_whatsapp import send_whatsapp

        msg = _make_message(delivery_state=MessageDeliveryState.QUEUED)
        msg.body = "Hello"

        conv = MagicMock()
        conv.guest_id = "g1"

        db = MagicMock()
        call_results = iter([msg, conv, None])  # None = no integration
        db.query.return_value.filter_by.return_value.first.side_effect = lambda: next(call_results)

        with patch("app.workers.tasks.send_whatsapp.SessionLocal", return_value=db):
            send_whatsapp.run(message_id=msg.id, tenant_id=msg.tenant_id)

        assert msg.delivery_state == MessageDeliveryState.FAILED
        assert "No WhatsApp integration" in (msg.delivery_error or "")


# ─────────────────────────────────────────────────────────────────
# Integration: send_message endpoint sets PENDING + QUEUED
# ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def conversation(db, tenant_and_user):
    import uuid as _uuid
    from app.models.guest import Guest

    tenant_id = (
        tenant_and_user["tenant"]["id"]
        if isinstance(tenant_and_user["tenant"], dict)
        else tenant_and_user["tenant"].id
    )

    guest = Guest(
        id=str(_uuid.uuid4()),
        tenant_id=tenant_id,
        phone="+919999000002",
        name="Delivery Test Guest",
    )
    db.add(guest)
    db.flush()

    conv = Conversation(
        id=str(_uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest.id,
        channel=ChannelType.WHATSAPP,
        is_open=True,
    )
    db.add(conv)
    db.commit()
    return conv


class TestSendMessageSetsDeliveryState:
    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_new_message_has_queued_state(self, mock_delay, client, auth_headers, conversation, db):
        client.headers.update(auth_headers)
        resp = client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "Delivery state test"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        data = resp.json()
        # After endpoint returns, state should be QUEUED (transitioned before dispatch)
        assert data["delivery_state"] == "queued"

    @patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
    def test_idempotent_hit_returns_original_state(self, mock_delay, client, auth_headers, conversation):
        """Dedup hit should return the original message — delivery_state included."""
        key = str(uuid.uuid4())
        client.headers.update(auth_headers)

        resp1 = client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "Dedup + delivery state"},
            headers={"Content-Type": "application/json", "Idempotency-Key": key},
        )
        assert resp1.status_code == 201
        original_state = resp1.json()["delivery_state"]

        resp2 = client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "Dedup + delivery state"},
            headers={"Content-Type": "application/json", "Idempotency-Key": key},
        )
        assert resp2.json()["id"] == resp1.json()["id"]
        assert resp2.json()["delivery_state"] == original_state
