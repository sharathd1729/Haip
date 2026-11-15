"""Flow "template" step (flow_engine._send_flow_template): an approved template with its values filled for the guest,
sent even when the 24-hour window is closed; opens the WhatsApp conversation if there is none; refuses with a reason."""
import uuid

import pytest

from app.api.v1.endpoints.messaging import TemplateStatus, WAFlow, WATemplate
from app.models.conversation import Conversation, Message
from app.models.flow_execution import WAFlowRun
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services.flow_engine import run_flow


@pytest.fixture
def queued(monkeypatch):
    out = []
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay", lambda **kw: out.append(kw))
    return out


def _world(db, components=None, vmap=None):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao", phone="+919886140372")
    tmpl = WATemplate(id=str(uuid.uuid4()), tenant_id=t.id, name="welcome_back", language="en", category="MARKETING",
                      status=TemplateStatus.APPROVED, meta_template_id="m1",
                      components=components or [{"type": "BODY", "text": "Hi {{1}}, we have new dates."}])
    db.add_all([g, tmpl])
    db.commit()
    nodes = [{"id": "n1", "type": "trigger", "content": "new_inquiry"},
             {"id": "n2", "type": "template", "template_id": tmpl.id,
              "variable_map": vmap if vmap is not None else {"body": {"1": {"source": "first_name", "fallback": "there"}}}},
             {"id": "n3", "type": "end"}]
    edges = [{"id": "e1", "from": "n1", "to": "n2"}, {"id": "e2", "from": "n2", "to": "n3"}]
    flow = WAFlow(id=str(uuid.uuid4()), tenant_id=t.id, name="F", nodes=nodes, edges=edges, trigger="new_inquiry", is_active=True)
    db.add(flow)
    db.commit()
    return t, g, tmpl, flow


def test_a_template_step_sends_with_the_guests_values_and_opens_the_chat(db, queued):
    t, g, tmpl, flow = _world(db)
    run_flow(db, t.id, flow, g.id)
    assert queued and queued[0]["template_name"] == "welcome_back" and queued[0]["variables"] == ["Ananya"]
    conv = db.query(Conversation).filter_by(tenant_id=t.id, guest_id=g.id).one()
    msg = db.query(Message).filter_by(conversation_id=conv.id).one()
    assert msg.body == "Hi Ananya, we have new dates." and msg.sender_kind == "system"
    assert db.query(WAFlowRun).filter_by(flow_id=flow.id, status="success").count() >= 1


def test_a_missing_value_skips_the_step_with_the_reason(db, queued):
    t, g, tmpl, flow = _world(db, vmap={})
    run_flow(db, t.id, flow, g.id)
    assert queued == []
    run = db.query(WAFlowRun).filter_by(flow_id=flow.id, status="skipped").one()
    assert "body {{1}}" in (run.detail or "")


def test_a_header_variable_is_refused_in_words(db, queued):
    comps = [{"type": "HEADER", "format": "TEXT", "text": "Offer for {{1}}"}, {"type": "BODY", "text": "Hi"}]
    t, g, tmpl, flow = _world(db, components=comps, vmap={"header": {"1": {"source": "first_name"}}})
    run_flow(db, t.id, flow, g.id)
    assert queued == []
    assert db.query(WAFlowRun).filter_by(flow_id=flow.id, status="skipped").count() == 1
