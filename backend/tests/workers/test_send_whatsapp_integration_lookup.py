"""
Tests for send_whatsapp.py's Integration.kind lookup — WhatsApp module
Phase 0 T0.1. The connect-key UI (integrations.py POST
/integrations/whatsapp_meta/connect-key) saves kind="whatsapp_meta"; this
task must find that row, not only the legacy "whatsapp" kind, matching the
lookup order already used in run_campaign.py/automation_engine.py/
sync_wa_templates.py.
"""
import uuid
from unittest.mock import patch, MagicMock
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection, MessageDeliveryState
from app.models.integration import Integration
from app.workers.tasks import send_whatsapp as mod


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_conversation_with_message(db, tenant_id, phone="+911234567890"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone=phone)
    db.add(g)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
        body="Hello", delivery_state=MessageDeliveryState.QUEUED,
    )
    db.add(msg)
    db.flush()
    return conv, msg


class _NoCloseSessionWrapper:
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


def test_send_whatsapp_finds_whatsapp_meta_kind(db):
    """A tenant onboarded purely via connect-key (kind='whatsapp_meta', no
    legacy 'whatsapp' row) must be able to send through this task."""
    t = _make_tenant(db)
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active",
        config={"phone_number_id": "123", "access_token": "tok"},
    )
    db.add(integration)
    conv, msg = _make_conversation_with_message(db, t.id)
    db.commit()

    fake_adapter = MagicMock()

    async def _fake_send_text(to, body):
        return {"messages": [{"id": "wamid.123"}]}
    fake_adapter.send_text = _fake_send_text

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch.object(mod, "get_wa_adapter", return_value=fake_adapter):
        mod.send_whatsapp.run(msg.id, t.id)

    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.SENT
    assert msg.channel_message_id == "wamid.123"


def test_send_whatsapp_falls_back_to_legacy_whatsapp_kind(db):
    """Existing tenants with only a legacy kind='whatsapp' row must keep working."""
    t = _make_tenant(db)
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp", status="active",
        config={"phone_number_id": "123", "access_token": "tok"},
    )
    db.add(integration)
    conv, msg = _make_conversation_with_message(db, t.id)
    db.commit()

    fake_adapter = MagicMock()

    async def _fake_send_text(to, body):
        return {"messages": [{"id": "wamid.456"}]}
    fake_adapter.send_text = _fake_send_text

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch.object(mod, "get_wa_adapter", return_value=fake_adapter):
        mod.send_whatsapp.run(msg.id, t.id)

    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.SENT


def test_send_whatsapp_no_integration_marks_failed(db):
    t = _make_tenant(db)
    conv, msg = _make_conversation_with_message(db, t.id)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        mod.send_whatsapp.run(msg.id, t.id)

    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.FAILED
