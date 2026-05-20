"""
B13 — E2E WhatsApp webhook → Guest + Conversation + Message chain test.

Tests the full path:
  POST /webhooks/whatsapp  →  Guest created/matched
                           →  Conversation created/matched
                           →  Message stored with correct fields

Covers:
  - New guest path (no prior guest with that phone)
  - Existing guest path (same phone sends a second message)
  - Media message (image with caption)
  - Delivery status callback (sent → delivered → read)
  - Duplicate message dedup (same wa_msg_id → not stored twice)
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


# ─── Fixtures ─────────────────────────────────────────────────────────────────

WA_PHONE_NUMBER_ID = "test_pn_id_001"
GUEST_PHONE = "+919876543210"
GUEST_NAME = "Test Guest"

# Minimal Meta webhook body
def _meta_payload(messages=None, statuses=None) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+911234567890",
                        "phone_number_id": WA_PHONE_NUMBER_ID,
                    },
                    "contacts": [{
                        "profile": {"name": GUEST_NAME},
                        "wa_id": GUEST_PHONE.lstrip("+"),
                    }],
                    "messages": messages or [],
                    "statuses": statuses or [],
                },
                "field": "messages",
            }],
        }],
    }


def _text_msg(body: str = "Hello, I want to book a room") -> dict:
    return {
        "from": GUEST_PHONE.lstrip("+"),
        "id": f"wamid.test_{uuid.uuid4().hex[:8]}",
        "timestamp": "1700000000",
        "text": {"body": body},
        "type": "text",
    }


def _image_msg(caption: str = "Check this view") -> dict:
    return {
        "from": GUEST_PHONE.lstrip("+"),
        "id": f"wamid.test_{uuid.uuid4().hex[:8]}",
        "timestamp": "1700000001",
        "type": "image",
        "image": {"id": "img123", "mime_type": "image/jpeg", "caption": caption, "link": ""},
    }


def _status_callback(wamid: str, status: str) -> dict:
    return {
        "id": wamid,
        "status": status,
        "timestamp": "1700000002",
        "recipient_id": GUEST_PHONE.lstrip("+"),
    }


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tenant_with_wa(db, client):
    """Create a tenant configured with the test WhatsApp phone number ID."""
    from app.models.tenant import Tenant
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Test Hotel",
        slug=f"test-hotel-{uuid.uuid4().hex[:6]}",
        whatsapp_phone_number_id=WA_PHONE_NUMBER_ID,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def test_new_guest_text_message_creates_chain(tenant_with_wa, db, client):
    """
    POST a text message from a new number.
    Asserts: Guest created, Conversation created, Message stored.
    """
    from app.models.guest import Guest
    from app.models.conversation import Conversation, Message

    msg = _text_msg()
    payload = _meta_payload(messages=[msg])

    with _mock_concierge():
        resp = client.post(
            "/api/v1/webhooks/whatsapp",
            json=payload,
            headers={"X-Hub-Signature-256": "sha256=mock"},   # bypass sig check in test mode
        )

    assert resp.status_code in (200, 202), resp.text

    guest = db.query(Guest).filter_by(phone=GUEST_PHONE).first()
    assert guest is not None, "Guest should be created"
    assert guest.name == GUEST_NAME

    conv = db.query(Conversation).filter_by(guest_id=guest.id).first()
    assert conv is not None, "Conversation should be created"
    assert conv.is_open is True

    stored_msg = db.query(Message).filter_by(channel_message_id=msg["id"]).first()
    assert stored_msg is not None, "Message should be stored"
    assert stored_msg.body == msg["text"]["body"]
    assert stored_msg.direction.value == "inbound"


def test_existing_guest_reuses_conversation(tenant_with_wa, db, client):
    """
    Second message from same number reuses existing Guest + open Conversation.
    """
    from app.models.guest import Guest
    from app.models.conversation import Conversation, Message

    msg1 = _text_msg("First message")
    msg2 = _text_msg("Second message")

    with _mock_concierge():
        client.post("/api/v1/webhooks/whatsapp", json=_meta_payload(messages=[msg1]),
                    headers={"X-Hub-Signature-256": "sha256=mock"})
        client.post("/api/v1/webhooks/whatsapp", json=_meta_payload(messages=[msg2]),
                    headers={"X-Hub-Signature-256": "sha256=mock"})

    guests = db.query(Guest).filter_by(phone=GUEST_PHONE).all()
    assert len(guests) == 1, "Should not create duplicate guests"

    convos = db.query(Conversation).filter_by(guest_id=guests[0].id).all()
    assert len(convos) == 1, "Should reuse the same open conversation"

    msgs = db.query(Message).filter_by(conversation_id=convos[0].id).all()
    assert len(msgs) == 2, "Both messages should be stored"


def test_duplicate_message_dedup(tenant_with_wa, db, client):
    """Posting the same wamid twice should store only one Message."""
    from app.models.conversation import Message

    msg = _text_msg()
    payload = _meta_payload(messages=[msg])

    with _mock_concierge():
        client.post("/api/v1/webhooks/whatsapp", json=payload,
                    headers={"X-Hub-Signature-256": "sha256=mock"})
        client.post("/api/v1/webhooks/whatsapp", json=payload,
                    headers={"X-Hub-Signature-256": "sha256=mock"})

    count = db.query(Message).filter_by(channel_message_id=msg["id"]).count()
    assert count == 1, "Duplicate wa message should be deduped"


def test_media_message_stored(tenant_with_wa, db, client):
    """Image message with caption is stored with media_type=image."""
    from app.models.conversation import Message

    msg = _image_msg("Great view from the balcony!")
    payload = _meta_payload(messages=[msg])

    with _mock_concierge():
        resp = client.post("/api/v1/webhooks/whatsapp", json=payload,
                           headers={"X-Hub-Signature-256": "sha256=mock"})

    stored = db.query(Message).filter_by(channel_message_id=msg["id"]).first()
    assert stored is not None
    assert stored.media_type == "image"
    assert stored.body == "Great view from the balcony!"


def test_status_callback_advances_delivery_state(tenant_with_wa, db, client):
    """
    After storing an outbound message, status callbacks advance delivery_state:
    sent → delivered → read
    """
    from app.models.conversation import Message, MessageDeliveryState
    import uuid as _uuid

    # Inject a fake outbound message directly
    from app.models.guest import Guest
    from app.models.conversation import Conversation, MessageDirection, ChannelType

    guest = Guest(id=str(_uuid.uuid4()), tenant_id=tenant_with_wa.id, phone="+910000000001", name="Out Guest")
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(_uuid.uuid4()), tenant_id=tenant_with_wa.id,
                        guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    wamid = f"wamid.outbound_{_uuid.uuid4().hex[:8]}"
    msg = Message(
        id=str(_uuid.uuid4()), tenant_id=tenant_with_wa.id,
        conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
        channel=ChannelType.WHATSAPP, body="Hi there!", channel_message_id=wamid,
        delivery_state=MessageDeliveryState.SENT,
    )
    db.add(msg)
    db.commit()

    # Send delivered callback
    resp = client.post(
        "/api/v1/webhooks/whatsapp",
        json=_meta_payload(statuses=[_status_callback(wamid, "delivered")]),
        headers={"X-Hub-Signature-256": "sha256=mock"},
    )
    assert resp.status_code in (200, 202)
    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.DELIVERED

    # Send read callback
    client.post("/api/v1/webhooks/whatsapp",
                json=_meta_payload(statuses=[_status_callback(wamid, "read")]),
                headers={"X-Hub-Signature-256": "sha256=mock"})
    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.READ


def test_status_never_goes_backwards(tenant_with_wa, db, client):
    """Read → delivered callback should not regress state to delivered."""
    from app.models.conversation import Message, MessageDeliveryState
    import uuid as _uuid
    from app.models.guest import Guest
    from app.models.conversation import Conversation, MessageDirection, ChannelType

    guest = Guest(id=str(_uuid.uuid4()), tenant_id=tenant_with_wa.id, phone="+910000000002", name="G")
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(_uuid.uuid4()), tenant_id=tenant_with_wa.id,
                        guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    wamid = f"wamid.regress_{_uuid.uuid4().hex[:8]}"
    msg = Message(
        id=str(_uuid.uuid4()), tenant_id=tenant_with_wa.id,
        conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
        channel=ChannelType.WHATSAPP, body="Hi!", channel_message_id=wamid,
        delivery_state=MessageDeliveryState.READ,
    )
    db.add(msg)
    db.commit()

    # Send delivered (backward) — should not regress
    client.post("/api/v1/webhooks/whatsapp",
                json=_meta_payload(statuses=[_status_callback(wamid, "delivered")]),
                headers={"X-Hub-Signature-256": "sha256=mock"})
    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.READ, "State should not go backward"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _mock_concierge():
    """Prevent concierge_draft from being queued during tests."""
    return patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async")
