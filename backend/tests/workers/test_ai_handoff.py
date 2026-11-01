"""The guest asked for a person (STOP / wants_human / "talk to a human"): AI off on the thread, older drafts can no longer be
approved, one audit row, and somebody owns the callback (services/ai_handoff.py). Real case: Ratha, 31 Oct 2026."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.task import Task
from app.models.user import UserRole
from app.services import ai_handoff, chat_phone_capture
from tests.test_increment1_defect_specs import _h, _tenant, _user
from tests.workers.test_agent_consult_flow import add_inbound, run_turn, setup_thread


def _old_draft(db, t, c, body="Hubli is a custom trip... our team will check the route"):
    m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="outbound", channel="whatsapp",
                body=body, is_ai_generated=True, was_approved=None,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    db.add(m)
    db.commit()
    return m


def _audits(db, tenant_id, conv_id):
    return db.query(AuditEvent).filter_by(tenant_id=tenant_id, action=ai_handoff.AUDIT_ACTION, target_id=conv_id).all()


def test_wants_human_turns_ai_off_and_old_drafts_cannot_be_approved(db, client):
    t, g, c, m = setup_thread(db, "Hubli trip for 4?")
    old = _old_draft(db, t, c)
    h = _h(_user(db, t.id, UserRole.MANAGER))
    m2 = add_inbound(db, t, c, "NO AI please.. human someone call....")
    t_id, c_id, old_id = t.id, c.id, old.id
    run_turn(db, t, c, m2, reply="I've passed your details to our team, someone will call you.",
             intent={"intent": "general", "wants_human": True})

    conv = db.get(Conversation, c_id)
    assert conv.ai_mode == "off"
    assert db.get(Message, old_id).was_approved is False
    newest = (db.query(Message).filter_by(conversation_id=c_id, is_ai_generated=True, sender_kind=None)
              .order_by(Message.created_at.desc()).first())
    assert newest.id != old_id and newest.was_approved is not False          # this turn's acknowledgement is kept
    (audit,) = _audits(db, t_id, c_id)
    assert audit.actor_user_id is None
    assert audit.payload["actor"] == "system" and audit.payload["reason"] == "wants_human"
    assert audit.payload["drafts_withdrawn"] == 1

    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as send:
        res = client.post(f"/api/v1/conversations/{c_id}/messages/{old_id}/approve", json={}, headers=h)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "draft_rejected"
    send.assert_not_called()

    detail = client.get(f"/api/v1/conversations/{c_id}", headers=h).json()
    assert detail["ai_enabled"] is False and detail["ai_off_reason"] == "guest asked for a person"

    # The guest writes again: no new AI draft while it is off.
    t, c = db.get(type(t), t_id), db.get(Conversation, c_id)
    before = db.query(Message).filter_by(conversation_id=c_id, is_ai_generated=True).count()
    run_turn(db, t, c, add_inbound(db, t, c, "hello?"), reply="Sure!")
    assert db.query(Message).filter_by(conversation_id=c_id, is_ai_generated=True).count() == before

    # A person turns it back on: the banner goes, the switch shows on.
    with patch("app.services.push_service.send_to_tenant"):
        assert client.patch(f"/api/v1/conversations/{c_id}", json={"ai_enabled": True}, headers=h).status_code == 200
    detail = client.get(f"/api/v1/conversations/{c_id}", headers=h).json()
    assert detail["ai_enabled"] is True and detail["ai_off_reason"] is None


def test_escalation_human_request_turns_ai_off(db):
    t, g, c, m = setup_thread(db, "I want to talk to a human")
    g_id = g.id
    run_turn(db, t, c, m, reply="Sure, connecting you.", intent={"intent": "general"})
    conv = db.query(Conversation).filter_by(guest_id=g_id).one()
    assert conv.ai_mode == "off"
    assert _audits(db, conv.tenant_id, conv.id)[0].payload["reason"] in ("human_request", "wants_human")


def test_an_ordinary_turn_leaves_the_ai_on(db):
    t, g, c, m = setup_thread(db, "What time can we leave Bengaluru?")
    g_id = g.id
    run_turn(db, t, c, m, reply="Trips start in the morning.", intent={"intent": "faq_answer"})
    conv = db.query(Conversation).filter_by(guest_id=g_id).one()
    assert conv.ai_mode != "off" and not _audits(db, conv.tenant_id, conv.id)


def _lead(db, t, c, owner=None):
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=c.guest_id, assigned_to=owner)
    db.add(inq)
    c.inquiry_id = inq.id
    db.commit()
    return inq


def test_unowned_lead_in_manual_mode_gets_a_callback_task_and_managers_are_pushed(db):
    t, g, c, m = setup_thread(db)
    mgr = _user(db, t.id, UserRole.MANAGER)
    inq = _lead(db, t, c)
    with patch("app.services.push_service.send_to_tenant") as push:
        assert ai_handoff.turn_off(db, t, c, "guest_stop") is True
    db.refresh(inq)
    assert inq.assigned_to is None                                            # manual mode: nobody is auto-assigned
    (task,) = db.query(Task).filter_by(tenant_id=t.id, guest_id=g.id, is_done=False).all()
    assert task.title.startswith("Call back") and task.priority == "high" and task.kind == "call"
    assert task.due_date is not None and task.inquiry_id == inq.id
    assert any(call.kwargs.get("user_id") == mgr.id for call in push.call_args_list)

    # Saying it again changes nothing: no second audit row, no second task.
    with patch("app.services.push_service.send_to_tenant"):
        assert ai_handoff.turn_off(db, t, c, "guest_stop") is False
    assert len(_audits(db, t.id, c.id)) == 1
    assert db.query(Task).filter_by(tenant_id=t.id, guest_id=g.id).count() == 1


def test_unowned_lead_in_round_robin_mode_is_assigned(db):
    t, g, c, m = setup_thread(db)
    t.lead_assignment_config = {"mode": "round_robin"}
    agent = _user(db, t.id, UserRole.RESERVATIONS)
    inq = _lead(db, t, c)
    with patch("app.services.push_service.send_to_tenant") as push:
        ai_handoff.turn_off(db, t, c, "wants_human")
    db.refresh(inq)
    assert inq.assigned_to == agent.id
    task = db.query(Task).filter_by(tenant_id=t.id, guest_id=g.id).one()
    assert task.assigned_to == agent.id
    assert all(call.kwargs.get("user_id") == agent.id for call in push.call_args_list)


def test_turn_off_touches_only_its_own_tenant(db):
    t1, _, c1, _ = setup_thread(db)
    t2, _, c2, _ = setup_thread(db)
    d1, d2 = _old_draft(db, t1, c1), _old_draft(db, t2, c2)
    with patch("app.services.push_service.send_to_tenant"):
        ai_handoff.turn_off(db, t1, c1, "guest_stop")
    db.refresh(d1); db.refresh(d2); db.refresh(c2)
    assert d1.was_approved is False and d2.was_approved is None and c2.ai_mode != "off"
    assert not _audits(db, t2.id, c2.id)
    assert ai_handoff.off_reason(db, t2.id, c1) is None                    # another tenant's id never reads t1's audit


@pytest.mark.parametrize("text,stop", [
    ("STOP", True), (" stop. ", True), ("Stop!", True), ("unsubscribe", True), ("बंद करो", True),
    ("cancel my booking", False), ("cancel", False), ("Our first stop is Hubli", False), ("stop by at 5?", False),
    ("NO AI please.. STOP calling", False), ("", False), (None, False),
])
def test_only_a_whole_message_stop_counts(text, stop):
    assert ai_handoff.is_stop_message(text) is stop


# ── The WhatsApp webhook path ───────────────────────────────────────────────

def _inbound(db, tenant, wamid, body, number="919845012345"):
    from app.workers.tasks.whatsapp import _handle_inbound_message
    msg = {"from": number, "id": wamid, "type": "text", "text": {"body": body}}
    with patch("app.services.push_service.send_to_tenant"), \
         patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"), \
         patch("redis.Redis.from_url", side_effect=RuntimeError("no redis in tests")), \
\
         patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async"):
        _handle_inbound_message(db, tenant, msg, [{"wa_id": number, "profile": {"name": "Ganessh"}}])


def _wa_conv(db, tenant_id):
    return db.query(Conversation).filter_by(tenant_id=tenant_id, channel=ChannelType.WHATSAPP).one()


def test_whatsapp_stop_turns_ai_off_and_withdraws_drafts(db):
    t = _tenant(db)
    _inbound(db, t, "wamid.h1", "Can we go to Hubli?")
    c = _wa_conv(db, t.id)
    d = _old_draft(db, t, c)
    _inbound(db, t, "wamid.h2", "STOP")
    db.refresh(c); db.refresh(d)
    assert c.ai_mode == "off" and d.was_approved is False
    assert _audits(db, t.id, c.id)[0].payload["reason"] == "guest_stop"


def test_cancel_my_booking_does_not_turn_the_ai_off(db):
    t = _tenant(db)
    _inbound(db, t, "wamid.c1", "Hi, trip in December")
    c = _wa_conv(db, t.id)
    d = _old_draft(db, t, c)
    _inbound(db, t, "wamid.c2", "cancel my booking")
    db.refresh(c); db.refresh(d)
    assert c.ai_mode != "off" and d.was_approved is None and not _audits(db, t.id, c.id)


def test_whatsapp_typed_number_becomes_an_extra_phone_signal(db):
    t = _tenant(db)
    _inbound(db, t, "wamid.p1", "Reach me anytime on: 9886012345")
    g = db.query(Guest).filter_by(tenant_id=t.id, is_deleted=False).one()
    values = {i.identity_value for i in db.query(GuestIdentity).filter_by(tenant_id=t.id, guest_id=g.id).all()}
    assert "+919886012345" in values and "+919845012345" in values


def test_a_typed_number_of_another_guest_is_not_merged(db):
    t = _tenant(db)
    other = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Someone else", phone="+919886054321")
    me = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Me", phone="+919845099999")
    db.add_all([other, me])
    db.commit()
    added = chat_phone_capture.capture_alternates(db, t.id, me.id, "call 9886054321 or +91 98450 99999")
    db.commit()
    db.refresh(other)
    assert added == [] and other.is_deleted is False
