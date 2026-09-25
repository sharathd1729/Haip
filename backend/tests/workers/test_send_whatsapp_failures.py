"""Why an inbox WhatsApp send failed must be visible, and a verdict from Meta
must not be retried.

Real incident (Ratha, Sep 2026): template messages to a lead showed a red
bubble reading "Max retries exceeded: Client error '400 Bad Request'". Meta's
actual reason was thrown away, the 400 was retried three times, and the guest's
number (+46463425978582, fourteen digits) was not a real WhatsApp number at all.
"""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.integration import Integration
from app.services import wa_campaign_delivery as delivery
from app.workers.tasks import send_whatsapp as send_mod


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _meta_error(status, code=None, message="boom"):
    body = {"error": {"code": code, "message": message}} if code else {}
    resp = httpx.Response(status, json=body, request=httpx.Request("POST", "https://graph.facebook.com/v20.0/1/messages"))
    return httpx.HTTPStatusError(f"{status}", request=resp.request, response=resp)


class FakeAdapter:
    def __init__(self, exc=None):
        self.exc, self.calls = exc, []

    async def send_template(self, to, template_name, language_code="en", components=None):
        self.calls.append({"kind": "template", "to": to, "components": components})
        if self.exc:
            raise self.exc
        return {"messages": [{"id": "wamid.OK"}]}

    async def send_text(self, to, body):
        self.calls.append({"kind": "text", "to": to})
        if self.exc:
            raise self.exc
        return {"messages": [{"id": "wamid.OK"}]}


@pytest.fixture()
def world(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active", config={"phone_number_id": "pn1"}))
    tmpl = WATemplate(id=str(uuid.uuid4()), tenant_id=tid, name="welcome", language="en", status=TemplateStatus.APPROVED,
                      components=[{"type": "BODY", "text": "Hi {{1}}, welcome to Ratha By Jade!"}])
    db.add(tmpl)
    db.commit()
    return SimpleNamespace(tid=tid, tmpl_id=tmpl.id)


def _message(db, w, phone="+919876500001", body="Hi Sharat, welcome", template=True):
    g = Guest(id=str(uuid.uuid4()), tenant_id=w.tid, name="Sharat", phone=phone)
    db.add(g); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=w.tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    msg = Message(id=str(uuid.uuid4()), tenant_id=w.tid, conversation_id=conv.id, direction="outbound", channel=ChannelType.WHATSAPP,
                  body=body, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued",
                  channel_metadata={"template_id": w.tmpl_id, "template_name": "welcome"} if template else {})
    db.add(msg); db.commit()
    return msg.id


def _run_template(db, w, msg_id, adapter, variables=("Sharat",)):
    with patch.object(send_mod, "SessionLocal", return_value=db), \
         patch.object(send_mod, "get_wa_adapter", return_value=adapter), \
         patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        send_mod.send_whatsapp_template.apply(kwargs={
            "message_id": msg_id, "tenant_id": w.tid, "template_name": "welcome", "language_code": "en", "variables": list(variables)})
    db.expire_all()
    return db.query(Message).get(msg_id)


def _run_text(db, w, msg_id, adapter):
    with patch.object(send_mod, "SessionLocal", return_value=db), \
         patch.object(send_mod, "get_wa_adapter", return_value=adapter), \
         patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        send_mod.send_whatsapp.apply(kwargs={"message_id": msg_id, "tenant_id": w.tid})
    db.expire_all()
    return db.query(Message).get(msg_id)


# ─── the reason is kept ──────────────────────────────────────────────────────

def test_a_template_send_that_meta_refuses_shows_metas_reason_and_is_not_retried(db, world):
    adapter = FakeAdapter(_meta_error(400, 131047, "Re-engagement message"))
    msg = _run_template(db, world, _message(db, world), adapter)
    assert len(adapter.calls) == 1                                   # a verdict, not a hiccup: no retries
    assert msg.delivery_state == MessageDeliveryState.FAILED
    assert "24-hour reply window is closed" in msg.delivery_error and "131047" in msg.delivery_error
    assert "Max retries" not in msg.delivery_error and "400 Bad Request" not in msg.delivery_error


def test_an_unknown_meta_error_shows_metas_own_words(db, world):
    adapter = FakeAdapter(_meta_error(400, 999001, "Template parameter count mismatch"))
    msg = _run_template(db, world, _message(db, world), adapter)
    assert "Template parameter count mismatch" in msg.delivery_error and len(adapter.calls) == 1


def test_a_temporary_meta_problem_is_retried_and_only_then_fails(db, world):
    adapter = FakeAdapter(_meta_error(503))
    msg = _run_template(db, world, _message(db, world), adapter)
    assert len(adapter.calls) == 4                                   # first try + 3 retries
    assert msg.delivery_state == MessageDeliveryState.FAILED


def test_a_free_text_send_outside_the_window_says_so_instead_of_retrying_five_times(db, world):
    adapter = FakeAdapter(_meta_error(400, 131047, "Re-engagement message"))
    msg = _run_text(db, world, _message(db, world, template=False), adapter)
    assert len(adapter.calls) == 1
    assert "24-hour reply window is closed" in msg.delivery_error and "Send an approved template" in msg.delivery_error


def test_a_send_that_works_still_works(db, world):
    adapter = FakeAdapter()
    msg = _run_template(db, world, _message(db, world), adapter)
    assert msg.delivery_state == MessageDeliveryState.SENT and msg.channel_message_id == "wamid.OK"


# ─── bad numbers never reach Meta ────────────────────────────────────────────

@pytest.mark.parametrize("phone", ["+46463425978582", "12345", ""])
def test_a_number_that_is_not_a_real_whatsapp_number_is_refused_before_sending(db, world, phone):
    adapter = FakeAdapter()
    msg = _run_template(db, world, _message(db, world, phone=phone), adapter)
    assert adapter.calls == []
    assert msg.delivery_state == MessageDeliveryState.FAILED
    assert "valid WhatsApp number" in msg.delivery_error or "no phone" in msg.delivery_error.lower()


def test_the_same_check_guards_free_text(db, world):
    adapter = FakeAdapter()
    msg = _run_text(db, world, _message(db, world, phone="+46463425978582", template=False), adapter)
    assert adapter.calls == [] and "valid WhatsApp number" in msg.delivery_error


# ─── the payload matches the template ────────────────────────────────────────

def test_the_body_values_go_out_as_the_templates_body_parameters(db, world):
    adapter = FakeAdapter()
    _run_template(db, world, _message(db, world), adapter)
    assert adapter.calls[0]["components"] == [{"type": "body", "parameters": [{"type": "text", "text": "Sharat"}]}]


def test_a_template_with_an_image_header_sends_the_image(db, world):
    tmpl = db.query(WATemplate).get(world.tmpl_id)
    tmpl.components = [{"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::h"]}}, tmpl.components[0]]
    tmpl.header_media_key = f"{world.tid}/wa_templates/h.jpg"
    db.commit()
    adapter = FakeAdapter()
    with patch("app.services.media_storage.get_presigned_media_url", return_value="https://files.example/h.jpg"):
        _run_template(db, world, _message(db, world), adapter)
    assert adapter.calls[0]["components"] == [
        {"type": "header", "parameters": [{"type": "image", "image": {"link": "https://files.example/h.jpg"}}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Sharat"}]},
    ]


def test_an_older_message_without_a_template_id_still_sends_body_values(db, world):
    adapter = FakeAdapter()
    _run_template(db, world, _message(db, world, template=False), adapter)
    assert adapter.calls[0]["components"] == [{"type": "body", "parameters": [{"type": "text", "text": "Sharat"}]}]


# ─── the helpers ─────────────────────────────────────────────────────────────

def test_retry_rules():
    assert delivery.is_retryable(_meta_error(503)) and delivery.is_retryable(_meta_error(429))
    assert not delivery.is_retryable(_meta_error(400, 131026)) and not delivery.is_retryable(_meta_error(401, 190))
    assert delivery.is_retryable(httpx.ConnectTimeout("slow"))              # a network blip: try again


def test_failure_text_is_plain_words_with_a_code_and_a_next_step():
    text = delivery.failure_text(_meta_error(400, 131030, "Recipient phone number not in allowed list"))
    assert "allowed list" in text and "131030" in text and "API Setup" in text
    assert "400" not in text.replace("131030", "")


# ─── the endpoint refuses what would fail ────────────────────────────────────

def _post(client, tu, conv_id, body):
    return client.post(f"/api/v1/conversations/{conv_id}/send-template", json=body,
                       headers={"Authorization": f"Bearer {tu['access_token']}"})


def test_the_endpoint_refuses_a_bogus_number_in_words(client, db, tenant_and_user, world):
    msg_id = _message(db, world, phone="+46463425978582")
    conv_id = db.query(Message).get(msg_id).conversation_id
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as delay:
        r = _post(client, tenant_and_user, conv_id, {"template_id": world.tmpl_id, "variables": ["Sharat"]})
    assert r.status_code == 422 and "valid WhatsApp number" in r.json()["detail"] and "+46463425978582" in r.json()["detail"]
    delay.assert_not_called()


def test_the_endpoint_refuses_the_wrong_number_of_values(client, db, tenant_and_user, world):
    conv_id = db.query(Message).get(_message(db, world)).conversation_id
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as delay:
        r = _post(client, tenant_and_user, conv_id, {"template_id": world.tmpl_id, "variables": []})
        assert r.status_code == 422 and "needs 1 value to fill in; 0 given" in r.json()["detail"]
        r = _post(client, tenant_and_user, conv_id, {"template_id": world.tmpl_id, "variables": ["a", "b"]})
        assert r.status_code == 422 and "2 given" in r.json()["detail"]
    delay.assert_not_called()


def test_the_endpoint_still_sends_when_everything_is_right(client, db, tenant_and_user, world):
    conv_id = db.query(Message).get(_message(db, world)).conversation_id
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as delay:
        r = _post(client, tenant_and_user, conv_id, {"template_id": world.tmpl_id, "variables": ["Sharat"]})
    assert r.status_code == 201 and "Sharat" in r.json()["body"]
    delay.assert_called_once()
