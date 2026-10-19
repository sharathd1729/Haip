"""A chat mirrored from the read-only personal WhatsApp bridge never gets a reply from the official WhatsApp number.

HAIP mirrors the agent's personal WhatsApp only to measure response time; it cannot send on that number. Before this fix
(priority list 2.6, 18 Oct 2026) three paths could still answer such a thread from the official Cloud API number:
  * the reply safety net (concierge.recover_missed_replies) re-queued the concierge for a bridge message an agent had not
    answered within 4 minutes, and on a tenant whose WhatsApp default is autonomous the concierge sent it;
  * concierge_draft itself had no bridge check;
  * the inbox send / send-template / retry / approve / ai-draft routes queued send_whatsapp on such threads.
Booking / quote / invoice messages (wa_booking_messages, quote_send_service) are deliberate official-number sends by staff and
are NOT blocked here. Celery queues and the Meta API are faked.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.workers.tasks import reply_recovery as rr

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

BRIDGE = "personal_bridge"


def _tid(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _ago(minutes):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _conv(db, tid, source=None, ai_mode="shadow"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                     source=source, ai_mode=ai_mode)
    db.add(c)
    db.flush()
    return c


def _msg(db, tid, c, direction="inbound", minutes=12, body="Is it free this weekend?", **kw):
    m = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction=direction, channel="whatsapp", body=body,
                created_at=_ago(minutes), **kw)
    db.add(m)
    db.flush()
    return m


def _autonomous(db, tid):
    db.query(Tenant).filter_by(id=tid).update({"wa_ai_mode_default": "autonomous", "wa_ai_confidence_threshold": 0.5})
    db.flush()


def _headers(db, tid, role=UserRole.OWNER):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=f"{role.value} user", email=f"{role.value}-{uuid.uuid4().hex[:6]}@test.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tid, 'role': role.value})}"}


def _other_tenant(db):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    return other.id


# ── 1. reply safety net ────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def recover(db, monkeypatch):
    sent, cache = MagicMock(), {}
    monkeypatch.setattr(rr, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(rr, "get_cached", lambda k: cache.get(k))
    monkeypatch.setattr(rr, "set_cached", lambda k, v, ttl=0: cache.__setitem__(k, v))
    monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.apply_async", sent)
    monkeypatch.setattr("app.services.concierge_service.mark_pending_draft", lambda *a, **k: None)
    return lambda tid: (rr.recover_missed_replies(tid), sent)


def test_recovery_never_requeues_a_bridge_thread_even_when_the_tenant_is_autonomous(db, tenant_and_user, recover):
    tid = _tid(tenant_and_user)
    _autonomous(db, tid)
    _msg(db, tid, _conv(db, tid, source=BRIDGE, ai_mode="shadow"), channel_metadata={"source": BRIDGE})
    db.commit()
    out, sent = recover(tid)
    assert out["queued"] == 0
    sent.assert_not_called()


def test_recovery_skips_a_guest_message_that_arrived_on_personal_whatsapp_in_an_official_thread(db, tenant_and_user, recover):
    # The bridge reuses a known lead's open official thread; the guest wrote to the agent's personal phone, so the official
    # number must not answer that message either.
    tid = _tid(tenant_and_user)
    _autonomous(db, tid)
    _msg(db, tid, _conv(db, tid), channel_metadata={"source": BRIDGE})
    db.commit()
    assert recover(tid)[0]["queued"] == 0


def test_recovery_still_requeues_an_official_thread(db, tenant_and_user, recover):
    tid = _tid(tenant_and_user)
    _autonomous(db, tid)
    c = _conv(db, tid)
    m = _msg(db, tid, c)
    db.commit()
    out, sent = recover(tid)
    assert out["queued"] == 1 and sent.call_args.kwargs["kwargs"]["message_id"] == m.id


def test_recovery_of_one_tenant_ignores_another_tenants_threads(db, tenant_and_user, recover):
    other = _other_tenant(db)
    _msg(db, other, _conv(db, other))
    _msg(db, other, _conv(db, other, source=BRIDGE))
    db.commit()
    assert recover(_tid(tenant_and_user))[0]["queued"] == 0


# ── 2. concierge_draft ─────────────────────────────────────────────────────────────────────────────────────

class _FakeLLM:
    async def complete(self, **kwargs):
        if kwargs.get("tools") and any((t.get("name") or "").startswith("classify") for t in kwargs["tools"]):
            return {"tool_use": {"intent": "faq_answer"}}
        return {"tool_use": {"intent": "faq_answer", "reply": "Check-in is from 2 PM.", "confidence": 0.95, "citations": [],
                             "needs_human": False}}


def _run_concierge(db, tid, conv, inbound):
    from app.workers.tasks.concierge_draft import concierge_draft
    with patch("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM()), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.concierge_draft.log") as log, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as wa_send:
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tid)
    return log, wa_send


def test_concierge_refuses_a_bridge_thread_and_logs_it(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _autonomous(db, tid)
    conv = _conv(db, tid, source=BRIDGE, ai_mode="shadow")
    inbound = _msg(db, tid, conv, minutes=1, body="Hi, what time is check-in?", channel_metadata={"source": BRIDGE})
    db.commit()
    log, wa_send = _run_concierge(db, tid, conv, inbound)
    wa_send.assert_not_called()
    assert db.query(Message).filter_by(conversation_id=conv.id, direction="outbound").count() == 0
    events = [c.args[0] for c in log.warning.call_args_list]
    assert "concierge_draft_refused_personal_bridge" in events


def test_concierge_still_answers_an_official_thread(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _autonomous(db, tid)
    conv = _conv(db, tid)
    inbound = _msg(db, tid, conv, minutes=1, body="Hi, what time is check-in?")
    db.commit()
    _run_concierge(db, tid, conv, inbound)
    assert db.query(Message).filter_by(conversation_id=conv.id, direction="outbound").count() == 1


# ── 3. inbox routes ────────────────────────────────────────────────────────────────────────────────────────

def _is_read_only(res):
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == "personal_bridge_read_only"


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_send_on_a_bridge_thread_is_refused_and_nothing_is_queued(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    db.commit()
    _is_read_only(client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Hello"}, headers=_headers(db, tid)))
    wa_send.assert_not_called()
    assert db.query(Message).filter_by(conversation_id=conv.id).count() == 0


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_an_internal_note_on_a_bridge_thread_is_still_allowed(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    db.commit()
    res = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "called him", "is_internal": True},
                      headers=_headers(db, tid))
    assert res.status_code == 201, res.text
    wa_send.assert_not_called()


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_send_on_an_official_thread_still_queues_the_send(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    db.commit()
    res = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Hello"}, headers=_headers(db, tid))
    assert res.status_code == 201, res.text
    wa_send.assert_called_once()


@patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay")
def test_send_template_on_a_bridge_thread_is_refused(tpl_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    db.commit()
    _is_read_only(client.post(f"/api/v1/conversations/{conv.id}/send-template", json={"template_id": str(uuid.uuid4()), "variables": []},
                              headers=_headers(db, tid)))
    tpl_send.assert_not_called()


@patch("app.api.v1.endpoints.conversations.concierge_draft.delay")
def test_ai_draft_on_a_bridge_thread_is_refused(draft, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    db.commit()
    _is_read_only(client.post(f"/api/v1/conversations/{conv.id}/messages/ai-draft", json={}, headers=_headers(db, tid)))
    draft.assert_not_called()


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_retry_on_a_bridge_thread_is_refused_and_the_message_stays_failed(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    m = _msg(db, tid, conv, direction="outbound", minutes=5, delivery_state=MessageDeliveryState.FAILED)
    db.commit()
    _is_read_only(client.post(f"/api/v1/conversations/{conv.id}/messages/{m.id}/retry", headers=_headers(db, tid)))
    wa_send.assert_not_called()
    db.refresh(m)
    assert m.delivery_state == MessageDeliveryState.FAILED


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_approve_on_a_bridge_thread_is_refused_and_the_draft_is_untouched(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    draft = _msg(db, tid, conv, direction="outbound", minutes=5, body="Draft", is_ai_generated=True, was_approved=None)
    db.commit()
    _is_read_only(client.post(f"/api/v1/conversations/{conv.id}/messages/{draft.id}/approve", json={}, headers=_headers(db, tid)))
    wa_send.assert_not_called()
    db.refresh(draft)
    assert draft.was_approved is None


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_a_role_without_send_rights_gets_403_on_a_bridge_thread(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    db.commit()
    res = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Hello"}, headers=_headers(db, tid, UserRole.MARKETING))
    assert res.status_code == 403
    wa_send.assert_not_called()


@patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay")
def test_another_workspaces_bridge_thread_is_not_found(wa_send, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = _other_tenant(db)
    conv = _conv(db, other, source=BRIDGE)
    m = _msg(db, other, conv, direction="outbound", minutes=5, delivery_state=MessageDeliveryState.FAILED)
    db.commit()
    h = _headers(db, tid)
    assert client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Hello"}, headers=h).status_code == 404
    assert client.post(f"/api/v1/conversations/{conv.id}/messages/{m.id}/retry", headers=h).status_code == 404
    wa_send.assert_not_called()


# ── 4. a guest who then writes to the official number ───────────────────────────────────────────────────────

def test_an_official_message_turns_the_guests_bridge_thread_into_an_official_one(db, tenant_and_user):
    # One open WhatsApp thread per guest: the official webhook reuses the bridge thread. Without this the guards above would
    # stop anyone from answering a message the guest sent to the official number.
    from app.workers.tasks.whatsapp import _handle_inbound_message
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, source=BRIDGE)
    phone = db.query(Guest).filter_by(id=conv.guest_id).one().phone
    from app.services.identity_service import add_signal
    add_signal(db, tid, conv.guest_id, "phone", phone, source="whatsapp_personal")
    db.commit()
    tenant = db.query(Tenant).filter_by(id=tid).one()
    with patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async"):
        _handle_inbound_message(db, tenant, {"id": f"wamid.{uuid.uuid4().hex}", "from": phone.lstrip("+"), "type": "text",
                                             "text": {"body": "Hi, is the caravan free?"}}, contacts=[])
    db.commit()
    db.refresh(conv)
    assert db.query(Message).filter_by(conversation_id=conv.id, direction="inbound").count() == 1
    assert conv.source is None and not conv.is_personal_bridge
