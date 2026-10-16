"""Personal WhatsApp bridge, WhatsApp-Web-style mirror: the agent's own replies, group chats, media (stored in object storage, i.e.
Cloudflare R2) and older history all land in the Inbox, but ONLY a live guest message makes a lead. Mirrored chats never count as
leads, never trigger a push or an AI draft, and tenants never see each other's chats."""
import base64
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401,F403
from tests.services.test_whatsapp_personal_service import _make_agent, _make_session, _make_tenant

from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.services import whatsapp_personal_service as svc


@pytest.fixture()
def world(db):
    t = _make_tenant(db)
    agent = _make_agent(db, t.id)
    return {"t": t, "agent": agent, "s": _make_session(db, t.id, agent.id)}


def _ago(minutes):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _ingest(db, w, **kw):
    kw.setdefault("bridge_message_id", f"m-{uuid.uuid4().hex[:8]}")
    return svc.ingest_chat_message(db, w["s"], **kw)


def _no_side_effects():
    return patch("app.services.push_service.send_to_tenant"), patch("app.services.leads_service.trigger_summary_refresh")


def test_the_agents_own_reply_is_an_outbound_message_and_not_a_lead(db, world):
    with _no_side_effects()[0] as push:
        m = _ingest(db, world, direction="outbound", from_phone="+919811122233", from_name="Priya", body="Your caravan is confirmed",
                    chat_jid="919811122233@s.whatsapp.net", occurred_at=_ago(5))
    assert m.direction.value == "outbound" and m.sender_id == world["agent"].id and m.sender_name == "Agent Raja"
    assert m.delivery_state.value == "sent" and m.channel_status == "sent"
    conv = db.query(Conversation).filter_by(id=m.conversation_id).one()
    assert conv.source == "personal_bridge" and conv.ai_mode == "off" and conv.channel_conversation_id == "919811122233@s.whatsapp.net"
    assert conv.first_response_at is not None
    guest = db.query(Guest).filter_by(id=conv.guest_id).one()
    assert guest.lead_identified_at is None and guest.phone == "+919811122233"    # the number is shown, but a mirrored chat is not a lead
    assert db.query(Inquiry).filter_by(tenant_id=world["t"].id).count() == 0
    push.assert_not_called()


def test_a_group_chat_is_one_conversation_with_the_senders_named(db, world):
    kw = dict(chat_jid="120363000000000001@g.us", chat_type="group", chat_name="Ratha trip - Coorg", body="Reached the site")
    a = _ingest(db, world, from_phone="+919800000001", from_name="Ravi", **kw)
    b = _ingest(db, world, from_phone="+919800000002", from_name="Meera", **kw)
    assert a.conversation_id == b.conversation_id
    conv = db.query(Conversation).filter_by(id=a.conversation_id).one()
    assert db.query(Guest).filter_by(id=conv.guest_id).one().name == "Ratha trip - Coorg"
    assert (a.sender_name, b.sender_name) == ("Ravi", "Meera") and a.channel_metadata["chat_type"] == "group"
    assert db.query(Inquiry).filter_by(tenant_id=world["t"].id).count() == 0 and conv.ai_mode == "off"


def test_history_keeps_the_original_time_and_makes_no_lead_push_or_duplicate(db, world):
    when = _ago(60 * 24 * 10)
    kw = dict(bridge_message_id="hist-1", from_phone="+919822233344", from_name="Arun", body="Is 20 Dec free?", chat_jid="919822233344@s.whatsapp.net",
              occurred_at=when, history=True)
    with _no_side_effects()[0] as push:
        m = _ingest(db, world, **kw)
        assert _ingest(db, world, **kw) is None                                   # the same message twice
    assert abs((m.created_at.replace(tzinfo=timezone.utc) - when).total_seconds()) < 1          # the message keeps its ORIGINAL time
    assert m.channel_metadata["history"] is True
    assert db.query(Inquiry).filter_by(tenant_id=world["t"].id).count() == 0
    push.assert_not_called()


def test_a_mirrored_chat_becomes_a_lead_when_the_person_writes_live(db, world):
    jid = "919833344455@s.whatsapp.net"
    _ingest(db, world, from_phone="+919833344455", from_name="Kiran", body="old chat", chat_jid=jid, occurred_at=_ago(60 * 48), history=True)
    assert db.query(Inquiry).filter_by(tenant_id=world["t"].id).count() == 0
    m = _ingest(db, world, from_phone="+919833344455", from_name="Kiran", body="Do you have a caravan this weekend?", chat_jid=jid)
    convs = db.query(Conversation).filter_by(tenant_id=world["t"].id).all()
    assert len(convs) == 1 and m.conversation_id == convs[0].id                   # same thread, not a second one
    guest = db.query(Guest).filter_by(id=convs[0].guest_id).one()
    assert guest.lead_identified_at is not None                                   # now a lead
    assert db.query(Inquiry).filter_by(tenant_id=world["t"].id, guest_id=guest.id).count() == 1


def test_a_live_guest_message_still_makes_a_lead_as_before(db, world):
    m = _ingest(db, world, from_phone="+919844455566", from_name="Sana", body="Hi, caravan rates?", chat_jid="919844455566@s.whatsapp.net")
    conv = db.query(Conversation).filter_by(id=m.conversation_id).one()
    assert conv.ai_mode == "shadow" and conv.inquiry_id is not None
    assert db.query(Guest).filter_by(id=conv.guest_id).one().lead_identified_at is not None


def test_a_live_message_with_no_phone_number_is_mirrored_not_a_lead_and_does_not_crash(db, world):
    m = _ingest(db, world, from_phone="", from_name="Hidden Number", body="Hello", chat_jid="1234567890@lid")
    conv = db.query(Conversation).filter_by(id=m.conversation_id).one()
    assert conv.ai_mode == "off" and db.query(Guest).filter_by(id=conv.guest_id).one().lead_identified_at is None
    assert db.query(Inquiry).filter_by(tenant_id=world["t"].id).count() == 0


def test_an_outbound_message_to_a_known_lead_joins_that_guest(db, world):
    first = _ingest(db, world, from_phone="+919855566677", from_name="Dev", body="Hello", chat_jid="919855566677@s.whatsapp.net")
    lead_guest = db.query(Conversation).filter_by(id=first.conversation_id).one().guest_id
    # a different chat id for the same number (WhatsApp's LID form) must still find the known guest, not make a second person
    out = _ingest(db, world, direction="outbound", from_phone="+919855566677", body="Sure, sending the brochure", chat_jid="555@lid")
    assert db.query(Conversation).filter_by(id=out.conversation_id).one().guest_id == lead_guest


def test_media_is_stored_in_object_storage_and_referenced(db, world):
    data = base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()
    with patch("app.services.media_storage.upload_personal_whatsapp_media", return_value="tenant/whatsapp_personal/s/img1.jpg") as up:
        m = _ingest(db, world, bridge_message_id="img1", from_phone="+919866677788", from_name="Lata", chat_jid="919866677788@s.whatsapp.net",
                    media_kind="image", media_mime="image/jpeg", media_base64=data, body="Our booking photo")
    assert m.media_url == "tenant/whatsapp_personal/s/img1.jpg" and m.media_type == "image" and m.body == "Our booking photo"
    args = up.call_args.args
    assert args[0] == world["t"].id and args[1] == world["s"].id and args[2] == "img1" and args[5] == "jpg"


def test_a_file_that_cannot_be_stored_leaves_a_readable_placeholder(db, world):
    data = base64.b64encode(b"voice").decode()
    with patch("app.services.media_storage.upload_personal_whatsapp_media", side_effect=RuntimeError("r2 down")):
        m = _ingest(db, world, bridge_message_id="v1", from_phone="+919877788899", chat_jid="919877788899@s.whatsapp.net", media_kind="audio",
                    media_mime="audio/ogg", media_base64=data)
    assert m is not None and m.media_url is None and m.body == "[voice message]"


def test_a_file_too_large_is_skipped_with_a_placeholder_and_a_reason(db, world):
    m = _ingest(db, world, bridge_message_id="big1", from_phone="+919888899900", chat_jid="919888899900@s.whatsapp.net", media_kind="video",
                media_skipped="too_large")
    assert m.media_url is None and m.body == "[video]" and m.channel_metadata["media_skipped"] == "too_large"


def test_two_workspaces_never_share_a_chat(db):
    w1, w2 = ({"t": t, "s": None} for t in (_make_tenant(db), _make_tenant(db)))
    for w in (w1, w2):
        a = _make_agent(db, w["t"].id)
        w["s"] = _make_session(db, w["t"].id, a.id)
    jid = "120363000000000009@g.us"
    m1 = _ingest(db, w1, chat_jid=jid, chat_type="group", chat_name="Team", from_phone="+919800000009", body="hi")
    m2 = _ingest(db, w2, chat_jid=jid, chat_type="group", chat_name="Team", from_phone="+919800000009", body="hi", bridge_message_id=m1.channel_message_id + "-b")
    assert m1.conversation_id != m2.conversation_id
    assert db.query(Conversation).filter_by(tenant_id=w1["t"].id).count() == 1 and db.query(Conversation).filter_by(tenant_id=w2["t"].id).count() == 1


class TestBridgeWebhooks:
    def _post(self, client, session, path, payload, secret="test-bridge-secret"):
        return client.post(f"/api/v1/webhooks/whatsapp-personal/{session.id}/{path}", json=payload, headers={"X-Bridge-Secret": secret})

    def test_history_endpoint_stores_a_batch_and_ignores_attached_files(self, client, db, world):
        batch = {"messages": [
            {"bridge_message_id": f"h{i}", "from_phone": "+919811100000", "from_name": "Old", "body": f"msg {i}", "chat_jid": "919811100000@s.whatsapp.net",
             "occurred_at": (_ago(1000 - i)).isoformat(), "media_kind": "image", "media_base64": "AAAA"}
            for i in range(3)]}
        r = self._post(client, world["s"], "history", batch)
        assert r.status_code == 200 and r.json() == {"status": "ok", "stored": 3, "received": 3}
        assert db.query(Message).filter_by(tenant_id=world["t"].id).count() == 3
        assert all(m.media_url is None for m in db.query(Message).filter_by(tenant_id=world["t"].id).all())

    def test_history_needs_the_right_secret(self, client, world):
        assert self._post(client, world["s"], "history", {"messages": []}, secret="wrong").status_code == 401

    def test_message_endpoint_accepts_the_new_fields(self, client, db, world):
        r = self._post(client, world["s"], "message", {"bridge_message_id": "w1", "from_phone": "+919822211100", "body": "reply from phone",
                                                       "direction": "outbound", "chat_jid": "919822211100@s.whatsapp.net", "from_name": "Guest"})
        assert r.status_code == 200
        assert db.query(Message).filter_by(channel_message_id="w1").one().direction.value == "outbound"

    def test_the_old_message_contract_still_works(self, client, db, world):
        r = self._post(client, world["s"], "message", {"bridge_message_id": "old1", "from_phone": "+919833322211", "from_name": "G", "body": "hello"})
        assert r.status_code == 200
        assert db.query(Message).filter_by(channel_message_id="old1").one().direction.value == "inbound"
