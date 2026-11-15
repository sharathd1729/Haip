"""WhatsApp interactive messages (services/wa_interactive.py) and keyword auto-replies (services/wa_keyword_replies.py).

Buttons / link button / list / location request are built within Meta's limits and sent by the send_whatsapp task;
the inbox can attach them; a keyword rule answers before the AI; workspaces never mix.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.encryption import encrypt_credentials
from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.services import wa_interactive, wa_keyword_replies


# ── payloads ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_payloads_match_metas_shapes():
    b = wa_interactive.payload({"kind": "buttons", "buttons": ["Check dates", "Prices"]}, "What would you like?")
    assert b["type"] == "button" and [x["reply"]["title"] for x in b["action"]["buttons"]] == ["Check dates", "Prices"]
    c = wa_interactive.payload({"kind": "cta_url", "title": "See villas", "url": "https://x.in/v"}, "Our stays")
    assert c["action"] == {"name": "cta_url", "parameters": {"display_text": "See villas", "url": "https://x.in/v"}}
    li = wa_interactive.payload({"kind": "list", "button": "Choose", "sections": [
        {"title": "Stays", "rows": [{"id": "dome", "title": "Dome Villa", "description": "8 guests"}]}]}, "Pick one")
    assert li["action"]["sections"][0]["rows"][0]["title"] == "Dome Villa"
    loc = wa_interactive.payload({"kind": "location_request"}, "Share your location")
    assert loc["type"] == "location_request_message"


@pytest.mark.parametrize("bad", [
    {"kind": "buttons", "buttons": ["A button title that is far too long"]},
    {"kind": "buttons", "buttons": ["a", "b", "c", "d"]},
    {"kind": "buttons", "buttons": ["Yes", "yes"]},
    {"kind": "cta_url", "title": "Open", "url": "http://insecure.example"},
    {"kind": "list", "button": "Choose", "sections": [{"rows": [{"id": str(i), "title": f"Row {i}"} for i in range(11)]}]},
])
def test_metas_limits_are_enforced(bad):
    with pytest.raises(ValidationError):
        wa_interactive.validate(bad)


# ── keyword replies ─────────────────────────────────────────────────────────────────────────────────────────────────

def _world(db, **ac):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao", phone="+919886140372")
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="PRICE", trigger="wa_message_received",
                       action="send_whatsapp_reply", is_active=True, run_count=0,
                       trigger_config={"keywords": ["price", "rates"], "exclude_keywords": ["refund"]},
                       action_config={"message": "Hi {first_name}! Which dates?", **ac})
    db.add_all([g, c, r])
    db.commit()
    return t, g, c, r


@pytest.fixture
def queued(monkeypatch):
    out = []
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp.delay", lambda **kw: out.append(kw))
    return out


def test_a_keyword_gets_the_reply_with_buttons(db, queued):
    t, g, c, r = _world(db, buttons=["This weekend", "Next month"])
    assert wa_keyword_replies.handle(db, t.id, g, c, "What are your RATES?")
    msg = db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one()
    assert msg.body == "Hi Ananya! Which dates?" and msg.sender_kind == "automation"
    assert msg.channel_metadata["interactive"] == {"kind": "buttons", "buttons": ["This weekend", "Next month"]}
    assert queued == [{"message_id": msg.id, "tenant_id": t.id}]
    db.refresh(r)
    assert r.run_count == 1


def test_excluded_words_and_no_match_leave_it_to_the_ai(db, queued):
    t, g, c, r = _world(db)
    assert not wa_keyword_replies.handle(db, t.id, g, c, "price of a refund?")
    assert not wa_keyword_replies.handle(db, t.id, g, c, "Is breakfast included?")
    assert queued == []


def test_once_per_person(db, queued):
    t, g, c, r = _world(db, once_per_person=True)
    assert wa_keyword_replies.handle(db, t.id, g, c, "price")
    assert not wa_keyword_replies.handle(db, t.id, g, c, "price again")
    assert len(queued) == 1


def test_rules_never_cross_workspaces(db, queued):
    t, g, c, r = _world(db)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert not wa_keyword_replies.handle(db, other.id, g, c, "price")


def test_rule_config_is_validated():
    with pytest.raises(ValidationError):
        wa_keyword_replies.validate_rule({"keywords": []}, {"message": "Hi"})
    with pytest.raises(ValidationError):
        wa_keyword_replies.validate_rule({"keywords": ["price"]},
                                         {"message": "Hi", "buttons": ["A"], "link": {"title": "Go", "url": "https://x.in"}})
    tc, ac = wa_keyword_replies.validate_rule({"keywords": [" price "]}, {"message": "Hi", "link": {"title": "Go", "url": "https://x.in"}})
    assert tc["keywords"] == ["price"] and ac["link"]["url"] == "https://x.in"


# ── the send task ───────────────────────────────────────────────────────────────────────────────────────────────────

class _NoClose:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


def test_the_send_task_sends_the_interactive_part(db):
    from app.workers.tasks import send_whatsapp as mod

    t, g, c, r = _world(db)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active",
                       config={"phone_number_id": "123"},
                       credentials_kms_blob=encrypt_credentials({"phone_number_id": "123", "access_token": "tok"})))
    msg = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.OUTBOUND,
                  channel=ChannelType.WHATSAPP, body="Pick one", delivery_state=MessageDeliveryState.QUEUED,
                  channel_metadata={"interactive": {"kind": "buttons", "buttons": ["Yes", "No"]}})
    db.add(msg)
    db.commit()
    sent = []
    adapter = MagicMock()

    async def send_interactive(to, interactive):
        sent.append(interactive)
        return {"messages": [{"id": "wamid.9"}]}
    adapter.send_interactive = send_interactive
    with patch.object(mod, "SessionLocal", return_value=_NoClose(db)), patch.object(mod, "get_wa_adapter", return_value=adapter):
        mod.send_whatsapp.run(msg.id, t.id)
    db.refresh(msg)
    assert sent[0]["type"] == "button" and msg.delivery_state == MessageDeliveryState.SENT


# ── the inbox ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.usefixtures("capabilities_seeded")
def test_the_inbox_can_attach_buttons_and_checks_them(client, db, tenant_and_user):
    from tests._wa_window import open_window

    tid = tenant_and_user["tenant"].id
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone="+919886140372")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.flush()
    open_window(db, c)
    db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        ok = client.post(f"/api/v1/conversations/{c.id}/messages", headers=h,
                         json={"body": "Which dates?", "interactive": {"kind": "buttons", "buttons": ["Weekend", "Weekday"]}})
        bad = client.post(f"/api/v1/conversations/{c.id}/messages", headers=h,
                          json={"body": "x", "interactive": {"kind": "cta_url", "title": "Go", "url": "http://x"}})
    assert ok.status_code == 201, ok.text
    assert bad.status_code == 422 and "https" in bad.json()["detail"]
    msg = db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one()
    assert msg.channel_metadata["interactive"]["buttons"] == ["Weekend", "Weekday"]


def test_blank_buttons_and_an_empty_link_are_ignored():
    tc, ac = wa_keyword_replies.validate_rule({"keywords": ["price"]},
                                              {"message": "Hi", "buttons": ["Weekend", "", " "], "link": {"title": "", "url": ""}})
    assert ac["buttons"] == ["Weekend"] and "link" not in ac


def test_the_inbound_task_answers_a_keyword_before_the_ai(db, queued, monkeypatch):
    from app.workers.tasks.whatsapp import _handle_inbound_message

    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    db.add(AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="PRICE", trigger="wa_message_received",
                          action="send_whatsapp_reply", is_active=True, run_count=0,
                          trigger_config={"keywords": ["price"]}, action_config={"message": "Which dates?"}))
    db.commit()
    monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.apply_async",
                        lambda *a, **k: pytest.fail("the AI must not answer a matched keyword"))
    _handle_inbound_message(db, t, {"id": "wamid.k1", "from": "919886140372", "type": "text",
                                    "text": {"body": "price please"}}, contacts=[])
    db.commit()
    out = db.query(Message).filter_by(tenant_id=t.id, direction="outbound").one()
    assert out.body == "Which dates?" and len(queued) == 1
    inbound = db.query(Message).filter_by(tenant_id=t.id, direction="inbound").one()
    assert inbound.automation_outcome == "matched_auto_replied"
