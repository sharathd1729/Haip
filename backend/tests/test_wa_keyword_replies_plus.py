"""WhatsApp keyword replies, round 2 (SMS9 / Wati parity): a PDF or photo on the reply, exact match, team-hours
rules (an away message that never counts as an answer), repeat after N hours, per-reply delivery counts."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.encryption import encrypt_credentials
from app.core.security import create_access_token
from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import inbox_service, wa_interactive, wa_keyword_replies


def _world(db, tc=None, **ac):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao", phone="+919886140372")
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add_all([g, c])
    db.commit()
    r = _rule(db, t.id, tc or {"keywords": ["hi", "hello"], "match": "exact"}, {"message": "Greetings from us!", **ac})
    return t, g, c, r


def _rule(db, tenant_id, tc, ac, name="Hello bot"):
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, trigger="wa_message_received",
                       action="send_whatsapp_reply", is_active=True, run_count=0, trigger_config=tc, action_config=ac)
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def queued(monkeypatch):
    out = []
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp.delay", lambda **kw: out.append(kw))
    return out


def _hours(monkeypatch, open_now: bool):
    monkeypatch.setattr("app.services.agent_consult_settings.in_business_hours", lambda tenant, now=None: open_now)


# ── exact match ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_exact_match_takes_only_the_bare_greeting(db, queued):
    t, g, c, r = _world(db)
    assert wa_keyword_replies.handle(db, t.id, g, c, "Hi!! 👋")
    assert not wa_keyword_replies.handle(db, t.id, g, c, "hi, is the villa free on Saturday?")
    assert len(queued) == 1


def test_word_match_is_still_the_default(db, queued):
    t, g, c, r = _world(db, tc={"keywords": ["hi"]})
    assert wa_keyword_replies.handle(db, t.id, g, c, "hi, is the villa free on Saturday?")


# ── a file on the reply ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_reply_carries_the_pdf_as_one_message(db, queued):
    t, g, c, _ = _world(db)
    key = f"{t.id}/wa_replies/abc.pdf"
    r2 = _rule(db, t.id, {"keywords": ["brochure"]}, {"message": "Here it is", "file": {"key": key, "kind": "document",
                                                                                     "filename": "Jade.pdf"}}, "PDF bot")
    assert wa_keyword_replies.handle(db, t.id, g, c, "brochure")
    msg = db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one()
    assert (msg.media_type, msg.media_url, msg.body) == ("document", key, "Here it is")
    assert msg.channel_metadata == {"automation_rule_id": r2.id, "filename": "Jade.pdf"}


def test_a_file_from_another_workspace_is_refused_and_never_sent(db, queued):
    t, g, c, _ = _world(db)
    foreign = {"key": "someone-else/wa_replies/x.pdf", "kind": "document"}
    with pytest.raises(ValueError):
        wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "file": foreign}, t.id)
    with pytest.raises(ValueError):
        wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "file": foreign})
    _rule(db, t.id, {"keywords": ["brochure"]}, {"message": "Here", "file": foreign}, "Old")  # written around the check
    assert wa_keyword_replies.handle(db, t.id, g, c, "brochure")
    msg = db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one()
    assert msg.media_url is None
    _, ac = wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "file": {"key": f"{t.id}/wa_replies/a.png",
                                                                                          "kind": "image"}}, t.id)
    assert ac["files"][0]["kind"] == "image" and "file" not in ac


class _NoClose:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


def _send(db, t, msg, adapter):
    from app.workers.tasks import send_whatsapp as mod

    db.add(Integration(id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active",
                       config={"phone_number_id": "123"},
                       credentials_kms_blob=encrypt_credentials({"phone_number_id": "123", "access_token": "tok"})))
    db.add(msg)
    db.commit()
    with patch.object(mod, "SessionLocal", return_value=_NoClose(db)), patch.object(mod, "get_wa_adapter", return_value=adapter), \
            patch("app.services.media_storage.get_presigned_media_url", return_value="https://files.example/signed"):
        mod.send_whatsapp.run(msg.id, t.id)
    db.refresh(msg)


def _out(t, c, **kw):
    return Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.OUTBOUND,
                   channel=ChannelType.WHATSAPP, delivery_state=MessageDeliveryState.QUEUED, **kw)


def test_the_send_task_signs_the_file_and_names_the_pdf(db):
    t, g, c, _ = _world(db)
    calls = []
    adapter = MagicMock()

    async def send_document(to, url, filename="", caption=""):
        calls.append((url, filename, caption))
        return {"messages": [{"id": "wamid.d"}]}
    adapter.send_document = send_document
    msg = _out(t, c, body="Here it is", media_type="document", media_url=f"{t.id}/wa_replies/a.pdf",
               channel_metadata={"filename": "Jade.pdf"})
    _send(db, t, msg, adapter)
    assert calls == [("https://files.example/signed", "Jade.pdf", "Here it is")]
    assert msg.delivery_state == MessageDeliveryState.SENT


def test_buttons_carry_the_photo_as_their_header(db):
    t, g, c, _ = _world(db)
    sent = []
    adapter = MagicMock()

    async def send_interactive(to, interactive):
        sent.append(interactive)
        return {"messages": [{"id": "wamid.i"}]}
    adapter.send_interactive = send_interactive
    msg = _out(t, c, body="Pick one", media_type="image", media_url=f"{t.id}/wa_replies/a.jpg",
               channel_metadata={"interactive": {"kind": "buttons", "buttons": ["Yes", "No"]}})
    _send(db, t, msg, adapter)
    assert sent[0]["header"] == {"type": "image", "image": {"link": "https://files.example/signed"}}
    assert wa_interactive.payload({"kind": "list", "button": "See", "sections": [{"rows": [{"id": "a", "title": "A"}]}]},
                                  "x", header={"type": "image"}).get("header") is None


def test_the_send_task_never_signs_another_workspaces_file(db):
    t, g, c, _ = _world(db)
    adapter = MagicMock()
    msg = _out(t, c, body="x", media_type="document", media_url="someone-else/wa_replies/a.pdf")
    _send(db, t, msg, adapter)
    assert msg.delivery_state == MessageDeliveryState.FAILED
    adapter.send_document.assert_not_called()


# ── team hours, away message, repeat ────────────────────────────────────────────────────────────────────────────────

def test_hours_rules_follow_the_team_hours(db, queued, monkeypatch):
    t, g, c, r = _world(db, tc={"keywords": ["price"], "hours": "open"})
    _hours(monkeypatch, False)
    assert not wa_keyword_replies.handle(db, t.id, g, c, "price")
    _hours(monkeypatch, True)
    assert wa_keyword_replies.handle(db, t.id, g, c, "price")


def test_an_away_message_never_counts_as_an_answer(db, queued, monkeypatch):
    t, g, c, _ = _world(db, tc={"keywords": ["zzz"]})
    away = _rule(db, t.id, {"reply_all": True, "hours": "closed"},
                 {"message": "We're closed now, back at 9am.", "repeat_after_hours": 12}, "Away")
    _hours(monkeypatch, False)
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="Is the villa free?", created_at=datetime.now(UTC) - timedelta(minutes=1)))
    db.commit()
    assert wa_keyword_replies.handle(db, t.id, g, c, "Is the villa free?")
    msg = db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one()
    assert msg.sender_kind == wa_keyword_replies.AWAY_KIND and msg.channel_metadata["automation_rule_id"] == away.id
    needs = inbox_service.apply_view(db, db.query(Conversation).filter(Conversation.tenant_id == t.id), t.id, "needs_reply", "")
    assert [x.id for x in needs.all()] == [c.id]  # still waiting for the team
    assert not wa_keyword_replies.handle(db, t.id, g, c, "hello?")  # once per 12 hours
    msg.created_at = datetime.now(UTC) - timedelta(hours=13)
    db.commit()
    assert wa_keyword_replies.handle(db, t.id, g, c, "hello?")


def test_a_matched_keyword_wins_over_a_reply_all_rule(db, queued, monkeypatch):
    t, g, c, _ = _world(db, tc={"reply_all": True})
    kw = _rule(db, t.id, {"keywords": ["price"]}, {"message": "Rates are on the site"}, "Price")
    assert wa_keyword_replies.handle(db, t.id, g, c, "price?")
    assert db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one().channel_metadata["automation_rule_id"] == kw.id


def test_new_options_are_validated():
    with pytest.raises(ValidationError):
        wa_keyword_replies.validate_rule({"keywords": ["x"], "match": "fuzzy"}, {"message": "Hi"})
    with pytest.raises(ValidationError):
        wa_keyword_replies.validate_rule({"keywords": ["x"], "hours": "night"}, {"message": "Hi"})
    with pytest.raises(ValidationError):
        wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "repeat_after_hours": 0})
    tc, ac = wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "file": {"key": ""}})
    assert tc["match"] == "word" and tc["hours"] == "any" and "file" not in ac


# ── endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _headers(db, tenant_id, role=UserRole.OWNER):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tenant_id, 'role': role.value})}"}


def test_upload_takes_a_pdf_and_refuses_other_files(client, db):
    t, *_ = _world(db)
    h = _headers(db, t.id)
    with patch("app.services.media_storage._put") as put, \
            patch("app.services.media_storage.get_presigned_media_url", return_value="https://files.example/p"):
        ok = client.post("/api/v1/automations/wa-reply-file", headers=h,
                         files={"file": ("../Jade brochure.pdf", b"%PDF-1.7 hello", "application/pdf")})
        bad = client.post("/api/v1/automations/wa-reply-file", headers=h,
                          files={"file": ("x.exe", b"MZ\x90\x00", "application/pdf")})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["key"].startswith(f"{t.id}/wa_replies/") and body["kind"] == "document" and body["filename"] == "Jade brochure.pdf"
    assert put.call_count == 1 and bad.status_code == 400


def test_upload_and_stats_need_an_owner_or_manager(client, db):
    t, *_ = _world(db)
    h = _headers(db, t.id, UserRole.CONCIERGE)
    assert client.post("/api/v1/automations/wa-reply-file", headers=h,
                       files={"file": ("a.pdf", b"%PDF-1", "application/pdf")}).status_code == 403
    assert client.get("/api/v1/automations/wa-reply-stats", headers=h).status_code == 403


def test_saving_a_rule_with_another_workspaces_file_is_refused(client, db):
    t, *_ = _world(db)
    r = client.post("/api/v1/automations", headers=_headers(db, t.id), json={
        "name": "PDF", "trigger": "wa_message_received", "trigger_config": {"keywords": ["pdf"]},
        "action": "send_whatsapp_reply", "action_config": {"message": "Here", "file": {"key": "other/wa_replies/a.pdf",
                                                                                     "kind": "document"}}})
    assert r.status_code == 422


def test_stats_count_each_reply_and_stay_in_the_workspace(client, db):
    t, g, c, r = _world(db)
    other, og, oc, orule = _world(db)
    for state in (MessageDeliveryState.READ, MessageDeliveryState.DELIVERED, MessageDeliveryState.SENT,
                  MessageDeliveryState.FAILED):
        db.add(_out(t, c, body="x", sender_kind="automation", channel_metadata={"automation_rule_id": r.id}))
        db.flush()
        db.query(Message).filter_by(tenant_id=t.id, delivery_state=MessageDeliveryState.QUEUED).update({"delivery_state": state})
    db.add(_out(other, oc, body="x", sender_kind="automation", channel_metadata={"automation_rule_id": orule.id}))
    db.commit()
    res = client.get("/api/v1/automations/wa-reply-stats?days=30", headers=_headers(db, t.id))
    assert res.status_code == 200, res.text
    assert res.json()["rules"] == [{"rule_id": r.id, "sent": 3, "delivered": 2, "read": 1, "failed": 1, "people": 1}]
