"""The honest AI scorecard: outcomes, consults by reason, answer times vs SLA, held-back reasons, conversion with/without a
consult; empty data gives None (never a fake percentage); owner/manager only; per tenant."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.agent_consult import AgentConsult
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Message
from app.models.user import UserRole
from tests.test_agent_consults_api import _world
from tests.test_increment1_defect_specs import _h

URL = "/api/v1/ai/scorecard"


def _outcome(db, w, outcome):
    m = Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=w.c.id, direction="outbound", channel="whatsapp",
                body="x", is_ai_generated=True, was_approved=None, ai_needs_human_reason="price leak: 'Rs 5'; low")
    db.add(m)
    db.flush()
    db.add(AIDraftOutcome(id=str(uuid.uuid4()), tenant_id=w.t.id, draft_message_id=m.id, outcome=outcome))


def test_empty_workspace_reports_no_data_not_zero(client, db):
    w = _world(db)
    db.delete(w.consult)
    db.commit()
    got = client.get(URL, headers=_h(w.mgr)).json()
    assert got["ai_replies"]["no_edit_share"] is None and got["answer_minutes"]["median"] is None
    assert got["answer_minutes"]["inside_sla_share"] is None and got["consults"]["opened"] == 0
    assert got["ai_replies"]["days"] == 7 and got["ai_replies"]["from"]


def test_the_numbers(client, db):
    w = _world(db)
    for o in ("sent_autonomous", "sent_autonomous", "sent_verbatim", "sent_edited", "rejected"):
        _outcome(db, w, o)
    now = datetime.now(timezone.utc)
    w.consult.status, w.consult.answered_at, w.consult.answer_mode = "answered", w.consult.created_at + timedelta(minutes=10), "edited"
    db.add(AgentConsult(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=w.c.id, reason_codes=["discount_request", "b2b_partner"],
                        question="q", evidence={}, status="expired", level="owner", sla_due_at=now, created_at=now - timedelta(hours=2)))
    db.commit()
    got = client.get(URL, params={"period": "30d"}, headers=_h(w.owner)).json()
    assert got["ai_replies"]["decided"] == 5 and got["ai_replies"]["no_edit_share"] == 0.6
    reasons = {r["code"]: r["count"] for r in got["consults"]["by_reason"]}
    assert reasons == {"discount_request": 2, "b2b_partner": 1} and got["consults"]["expired"] == 1
    assert got["answer_minutes"]["answered"] == 1 and got["answer_minutes"]["median"] == 10.0
    assert got["held_back"]["reasons"][0] == {"reason": "price leak", "count": 5}
    assert got["conversion"]["with_consult"]["leads"] >= 0 and got["consults"]["days"] == 30


def test_roles_and_tenants(client, db):
    w = _world(db)
    assert client.get(URL, headers=_h(w.foh)).status_code == 403
    assert client.get(URL, params={"period": "1y"}, headers=_h(w.owner)).status_code == 422
    other = _world(db)
    _outcome(db, w, "rejected")
    db.commit()
    assert client.get(URL, headers=_h(other.owner)).json()["ai_replies"]["rejected"] == 0
