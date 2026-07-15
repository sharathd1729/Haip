"""
WhatsApp module Phase 3, T3.2 -- closed-window "Send template" endpoint.
Previously a dead toast stub in the inbox UI; now a real send path.
"""
import uuid
from unittest.mock import patch
import pytest

from app.models.conversation import Conversation, ChannelType, MessageDeliveryState
from app.models.guest import Guest
from app.api.v1.endpoints.messaging import WATemplate, TemplateStatus


@pytest.fixture()
def wa_conversation(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="+919999000003")
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.commit()
    return conv


@pytest.fixture()
def approved_template(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="booking_confirmation", language="en",
        status=TemplateStatus.APPROVED,
        components=[{"type": "BODY", "text": "Hi {{1}}, your stay at {{2}} is confirmed."}],
    )
    db.add(tmpl)
    db.commit()
    return tmpl


def test_send_template_happy_path(client, db, tenant_and_user, wa_conversation, approved_template):
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as mock_delay:
        resp = client.post(
            f"/api/v1/conversations/{wa_conversation.id}/send-template",
            json={"template_id": approved_template.id, "variables": ["Priya", "Casa Aurora"]},
            headers=headers,
        )

    assert resp.status_code == 201
    resp_body = resp.json()
    assert "Priya" in resp_body["body"]
    assert "Casa Aurora" in resp_body["body"]
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs["template_name"] == "booking_confirmation"
    assert call_kwargs["variables"] == ["Priya", "Casa Aurora"]


def test_send_template_rejects_unapproved(client, db, tenant_and_user, wa_conversation):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="pending_tmpl", language="en",
        status=TemplateStatus.PENDING, components=[{"type": "BODY", "text": "Hi {{1}}"}],
    )
    db.add(tmpl)
    db.commit()
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

    resp = client.post(
        f"/api/v1/conversations/{wa_conversation.id}/send-template",
        json={"template_id": tmpl.id, "variables": ["X"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_send_template_rejects_non_whatsapp_channel(client, db, tenant_and_user, approved_template):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="IG Guest", phone="")
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.INSTAGRAM, is_open=True)
    db.add(conv)
    db.commit()

    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    resp = client.post(
        f"/api/v1/conversations/{conv.id}/send-template",
        json={"template_id": approved_template.id, "variables": ["X", "Y"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_send_template_cross_tenant_404(client, db, tenant_and_user, approved_template):
    other_tenant_conv_id = str(uuid.uuid4())   # doesn't exist for this tenant
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    resp = client.post(
        f"/api/v1/conversations/{other_tenant_conv_id}/send-template",
        json={"template_id": approved_template.id, "variables": []},
        headers=headers,
    )
    assert resp.status_code == 404
