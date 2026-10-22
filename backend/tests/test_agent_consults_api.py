"""Ask a manager: answering, taking over, settings, the escalation ladder and the work-queue item.

Per endpoint: happy path, a role without conversations.send (403), another tenant (404 / untouched). Celery sends are mocked.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.agent_consult import AgentConsult
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.knowledge import KnowledgeEntry
from app.models.task import Task
from app.models.user import UserRole
from app.services import agent_consult_notify, work_queue_service
from tests.test_increment1_defect_specs import _h, _tenant, _user

C = "/api/v1/consults"
S = "/api/v1/ai/consult-settings"


class W:
    pass


def _world(db, *, inbound_age=timedelta(minutes=2)):
    w = W()
    w.t = _tenant(db)
    w.owner = _user(db, w.t.id, UserRole.OWNER)
    w.mgr = _user(db, w.t.id, UserRole.MANAGER)
    w.foh = _user(db, w.t.id, UserRole.FOH)
    w.comp = _user(db, w.t.id, UserRole.COMPLIANCE)
    w.g = Guest(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Priya Sharma", phone="+919845600001",
                lead_identified_at=datetime.now(timezone.utc))
    db.add(w.g)
    db.flush()
    w.c = Conversation(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=w.g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(w.c)
    db.flush()
    w.inbound = Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=w.c.id, direction="inbound", channel="whatsapp",
                        body="Can we get a discount?", created_at=datetime.now(timezone.utc) - inbound_age)
    w.draft = Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=w.c.id, direction="outbound", channel="whatsapp",
                      body="We can offer 10% off!", is_ai_generated=True, was_approved=None, ai_intent="price_quote")
    db.add_all([w.inbound, w.draft])
    db.flush()
    w.consult = AgentConsult(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=w.c.id, guest_id=w.g.id, message_id=w.inbound.id,
                             draft_message_id=w.draft.id, channel="whatsapp", reason_codes=["discount_request"],
                             question="Can we get a discount?", proposed_answer=w.draft.body,
                             options=[{"id": "kit", "text": "Instead of a discount we can add the Culinary kit for you."}],
                             evidence={}, status="open", level="manager", sla_due_at=datetime.now(timezone.utc) + timedelta(minutes=15),
                             created_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    db.add(w.consult)
    db.commit()
    return w


@pytest.fixture()
def sends():
    out = []
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay", side_effect=lambda **kw: out.append(kw["message_id"])):
        yield out


def test_list_and_read_open_first(client, db, sends):
    w = _world(db)
    rows = client.get(C, headers=_h(w.foh)).json()
    assert [r["id"] for r in rows] == [w.consult.id]
    assert rows[0]["reasons"][0]["code"] == "discount_request" and rows[0]["window_open"] is True
    one = client.get(f"{C}/{w.consult.id}", headers=_h(w.mgr)).json()
    assert one["question"] == "Can we get a discount?" and one["guest_name"] == "Priya Sharma"


def test_approve_the_proposed_answer_sends_the_held_draft_once(client, db, sends):
    w = _world(db)
    res = client.post(f"{C}/{w.consult.id}/answer", json={"mode": "approve_proposed"}, headers=_h(w.mgr))
    assert res.status_code == 200, res.text
    assert res.json()["delivery"] == "queued" and sends == [w.draft.id]
    db.expire_all()
    d = db.get(Message, w.draft.id)
    assert d.was_approved is True and d.sender_id == w.mgr.id                    # a person approved it: human contact
    c = db.get(AgentConsult, w.consult.id)
    assert c.status == "answered" and c.answered_by == w.mgr.id
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="agent_consult.answered").count() == 1
    # A second manager is told someone already answered; nothing is sent twice.
    again = client.post(f"{C}/{w.consult.id}/answer", json={"mode": "edited", "text": "Hi"}, headers=_h(w.owner))
    assert again.status_code == 409 and sends == [w.draft.id]


def test_edit_and_send_and_save_to_kb_as_pending(client, db, sends):
    w = _world(db)
    res = client.post(f"{C}/{w.consult.id}/answer", headers=_h(w.foh),
                      json={"mode": "edited", "text": "We don't discount small trips, but we can add a kit.", "save_to_kb": True})
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(Message, w.draft.id).body == "We don't discount small trips, but we can add a kit."
    entry = db.get(KnowledgeEntry, res.json()["kb_entry_id"])
    assert entry.review_status == "pending" and entry.source_ref == f"consult:{w.consult.id}"   # the owner approves it


def test_an_option_answer(client, db, sends):
    w = _world(db)
    assert client.post(f"{C}/{w.consult.id}/answer", json={"mode": "option", "option_id": "nope"}, headers=_h(w.mgr)).status_code == 422
    assert client.post(f"{C}/{w.consult.id}/answer", json={"mode": "option", "option_id": "kit"}, headers=_h(w.mgr)).status_code == 200
    db.expire_all()
    assert "Culinary kit" in db.get(Message, w.draft.id).body


def test_window_closed_raises_a_reply_task_instead_of_sending(client, db, sends):
    w = _world(db, inbound_age=timedelta(hours=30))
    res = client.post(f"{C}/{w.consult.id}/answer", json={"mode": "edited", "text": "Here is the price"}, headers=_h(w.mgr))
    assert res.json()["delivery"] == "window_closed_task" and sends == []
    task = db.get(Task, res.json()["task_id"])
    assert task.title.startswith("Reply needed: window closed")


def test_take_over(client, db, sends):
    w = _world(db)
    assert client.post(f"{C}/{w.consult.id}/take-over", headers=_h(w.foh)).status_code == 200
    db.expire_all()
    assert db.get(AgentConsult, w.consult.id).status == "taken_over"
    assert db.get(Conversation, w.c.id).assigned_to == w.foh.id
    assert client.post(f"{C}/{w.consult.id}/take-over", headers=_h(w.mgr)).status_code == 409


def test_a_role_without_send_is_refused(client, db, sends):
    w = _world(db)
    assert client.get(C, headers=_h(w.comp)).status_code == 403
    assert client.post(f"{C}/{w.consult.id}/answer", json={"mode": "approve_proposed"}, headers=_h(w.comp)).status_code == 403
    assert sends == []


def test_another_tenants_consult_is_not_found(client, db, sends):
    w = _world(db)
    other = _world(db)
    assert client.get(f"{C}/{w.consult.id}", headers=_h(other.mgr)).status_code == 404
    assert client.post(f"{C}/{w.consult.id}/answer", json={"mode": "approve_proposed"}, headers=_h(other.mgr)).status_code == 404
    assert [r["id"] for r in client.get(C, headers=_h(other.mgr)).json()] == [other.consult.id]
    db.expire_all()
    assert db.get(AgentConsult, w.consult.id).status == "open" and sends == []


def test_answered_in_the_inbox_closes_the_consult(client, db, sends):
    w = _world(db)
    w.draft.was_approved = True
    w.draft.sender_id = w.mgr.id
    db.commit()
    rows = client.get(C, headers=_h(w.mgr)).json()
    assert rows[0]["status"] == "answered" and rows[0]["answer_mode"] == "inbox"


# ── settings ─────────────────────────────────────────────────────────────────

def test_owner_changes_settings_audited_and_only_through_this_endpoint(client, db):
    w = _world(db)
    got = client.get(S, headers=_h(w.mgr)).json()
    assert got["business_start"] == "09:00" and got["sla_minutes"] == 15 and "15 minutes" in got["preview"]["in_hours"]
    assert client.put(S, json={"sla_minutes": 20}, headers=_h(w.mgr)).status_code == 403
    res = client.put(S, json={"sla_minutes": 20, "business_end": "20:00"}, headers=_h(w.owner))
    assert res.status_code == 200 and res.json()["changed"]["sla_minutes"] == {"from": 15, "to": 20}
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ai.consult_settings_changed").count() == 1
    assert client.put(S, json={"business_start": "9am"}, headers=_h(w.owner)).status_code == 422
    assert client.get(S, headers=_h(w.foh)).status_code == 403
    for key in ("agent_consult", "agent_policy", "sales_playbook"):
        assert client.patch("/api/v1/tenants/me", json={"brand_config": {key: {}}}, headers=_h(w.owner)).status_code == 422
    other = _world(db)
    assert client.get(S, headers=_h(other.owner)).json()["sla_minutes"] == 15


# ── escalation ladder + work queue ───────────────────────────────────────────

def test_unanswered_consult_climbs_to_the_owner_then_expires_with_a_callback_task(db):
    w = _world(db)
    noon = datetime(2026, 10, 22, 6, 30, tzinfo=timezone.utc)          # 12:00 IST, business hours
    w.consult.sla_due_at = noon - timedelta(minutes=1)
    db.commit()
    with patch("app.services.push_service.send_to_tenant") as push:
        assert agent_consult_notify.escalate(db, w.t, noon)["escalated"] == 1
        db.refresh(w.consult)
        assert w.consult.level == "owner" and any(c.kwargs.get("user_id") == w.owner.id for c in push.call_args_list)
        assert agent_consult_notify.escalate(db, w.t, noon)["escalated"] == 0          # not due again yet
        later = noon + timedelta(minutes=16)
        assert agent_consult_notify.escalate(db, w.t, later)["expired"] == 1
    db.refresh(w.consult)
    assert w.consult.status == "expired"
    assert db.get(Task, w.consult.task_id).title.startswith("Call back: unanswered question")
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="agent_consult.escalated").count() == 1


def test_escalation_is_per_tenant(db):
    w = _world(db)
    other = _world(db)
    w.consult.sla_due_at = other.consult.sla_due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    with patch("app.services.push_service.send_to_tenant"):
        agent_consult_notify.escalate(db, w.t)
    db.refresh(other.consult)
    assert other.consult.level == "manager"


def test_an_open_consult_is_the_first_item_on_my_day(db):
    w = _world(db)
    res = work_queue_service.build(db, w.t, None)
    assert res["counts"]["consult"] == 1 and res["items"][0]["kind"] == "consult"
    assert res["items"][0]["href"].endswith(f"consult={w.consult.id}") and res["items"][0]["lane"] == "now"
    other = _world(db)
    assert work_queue_service.build(db, other.t, None)["counts"]["consult"] == 1
