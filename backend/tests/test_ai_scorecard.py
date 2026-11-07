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


# ── by_intent (Phase 1 step 5): per-intent draft outcomes, always the last 30 days ─────────────────────────────────────────

def _intent_row(db, w, intent, outcome, *, edit=None, secs=None, age_days=1):
    m = Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=w.c.id, direction="outbound", channel="whatsapp",
                body="x", is_ai_generated=True, ai_intent=intent)
    db.add(m)
    db.flush()
    db.add(AIDraftOutcome(id=str(uuid.uuid4()), tenant_id=w.t.id, draft_message_id=m.id, outcome=outcome, intent=intent,
                          edit_distance_pct=edit, time_to_action_sec=secs,
                          created_at=datetime.now(timezone.utc) - timedelta(days=age_days)))


def _faq_month(db, w):
    """faq_answer: 20 autonomous + 4 verbatim + 4 edited + 2 rejected = 30 decided (10 reviewed), 2 expired; price_quote: 3."""
    for _ in range(20):
        _intent_row(db, w, "faq_answer", "sent_autonomous", secs=0)
    for s in (60, 120, 180, 240):
        _intent_row(db, w, "faq_answer", "sent_verbatim", secs=s)
    for e, s in ((90.0, 300), (80.0, 300), (70.0, 300), (60.0, 300)):
        _intent_row(db, w, "faq_answer", "sent_edited", edit=e, secs=s)
    for _ in range(2):
        _intent_row(db, w, "faq_answer", "rejected", secs=600)
    for _ in range(2):
        _intent_row(db, w, "faq_answer", "expired", secs=86400)
    for o in ("sent_verbatim", "rejected", "sent_autonomous"):
        _intent_row(db, w, "price_quote", o, secs=30)
    _intent_row(db, w, "faq_answer", "rejected", age_days=40)   # outside the 30 days
    db.commit()


def test_by_intent_service_numbers(db):
    from app.services import ai_scorecard
    w = _world(db)
    _faq_month(db, w)
    got = ai_scorecard.build(db, w.t, "7d")["by_intent"]
    assert got["days"] == 30 and got["min_decided"] == 30 and got["from"]
    faq, price = got["intents"]
    assert faq["intent"] == "faq_answer" and faq["decided"] == 30 and faq["drafts"] == 32 and faq["too_few"] is False
    assert faq["sent_autonomous"] == 20 and faq["reviewed"] == 10
    # verbatim / edited / rejected over human-reviewed drafts only, never the autonomous sends
    assert (faq["verbatim_share"], faq["edited_share"], faq["rejected_share"]) == (0.4, 0.4, 0.2)
    assert faq["expired_share"] == round(2 / 32, 3)
    assert faq["median_edit_pct"] in (70.0, 80.0)
    assert faq["median_action_sec"] == 300.0   # reviewed drafts only: autonomous 0s and expired 24h are left out
    assert price["intent"] == "price_quote" and price["decided"] == 3 and price["too_few"] is True
    assert price["verbatim_share"] is None and price["median_action_sec"] is None


def test_by_intent_service_tenant_isolation(db):
    from app.services import ai_scorecard
    w, other = _world(db), _world(db)
    _faq_month(db, w)
    assert ai_scorecard.build(db, other.t, "30d")["by_intent"]["intents"] == []


def test_by_intent_endpoint_roles_and_tenants(client, db):
    w, other = _world(db), _world(db)
    _faq_month(db, w)
    _intent_row(db, w, None, "rejected")   # a draft written before intents were stored
    db.commit()
    rows = {r["intent"]: r for r in client.get(URL, headers=_h(w.mgr)).json()["by_intent"]["intents"]}
    assert rows["faq_answer"]["decided"] == 30 and rows["unknown"]["too_few"] is True
    assert client.get(URL, headers=_h(w.foh)).status_code == 403
    assert client.get(URL, headers=_h(other.owner)).json()["by_intent"]["intents"] == []
