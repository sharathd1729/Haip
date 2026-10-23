"""A collaboration / barter / influencer request goes to a person who answers yes or no (Rathaa, Oct 2026).

Live bug (synthetic copy of the thread): the guest asked "Can you give barter collaboration" weeks after her first "Hey!". The AI
answered "the team will reach out" four times in four weeks, nobody did, no task existed, and the lead ended Lost instead of in
the tenant's collaboration stage. Now: a consult holds the AI's draft and tells the team (one holding line, never twice in a row);
where no consult can open, ONE task per conversation and no new promise after the first; the lead autopilot moves the lead to the
collab-entry stage and never auto-Losts it while the request waits.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.agent_consult import AgentConsult
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import agent_escalation_rules as r
from app.services import collab_requests, lead_autopilot_service
from app.services import lead_autopilot_rules as rules
from app.services.lead_auto_create import is_collab_message, is_collab_request
from app.services.lead_autopilot_rules import StageMap
from app.workers.tasks.concierge_draft import concierge_draft
from tests.services._autopilot_fixtures import NOW, lead, msg, settings, tenant


@pytest.mark.parametrize("text", ["Can you give barter collaboration", "Interested in a collab?", "I'm an influencer",
                                  "Do you do barter stays", "We are content creators", "paid promotion for your caravan"])
def test_collab_requests(text):
    assert is_collab_request(text)


@pytest.mark.parametrize("text", ["My partner and I want to travel", "Is the content of the trip fixed?", "Hey!",
                                  "What is your B2B rate"])
def test_not_collab_requests(text):
    assert not is_collab_request(text)


def test_barter_and_influencer_now_route_a_first_message_too():
    assert is_collab_message("Barter stay possible?") and is_collab_message("I'm an influencer")


def test_the_consult_reason_is_stable_and_labelled():
    v = r.evaluate(r.TurnSignals(burst_text="Can you give barter collaboration", intent="general", confidence=0.95,
                                 reply_text="Our team reviews every collaboration request.", collab_request=True))
    assert "collab_request" in v.reasons and r.labels(["collab_request"])[0]["label"].startswith("Collaboration")
    assert "collab_request" not in r.evaluate(r.TurnSignals(burst_text="Hi", confidence=0.95, reply_text="Hello!")).reasons


# ── pending(): the ONE contact rule decides whether a person answered ─────────

def test_pending_until_a_person_answers_and_never_across_tenants(db):
    t, s = tenant(db)
    g, inq, conv = lead(db, t.id, s["general_enquiry"])
    ask = msg(db, t.id, conv, "Can you give barter collaboration", ago=timedelta(days=5))
    msg(db, t.id, conv, "Our team will reach out.", inbound=False, ago=timedelta(days=5) - timedelta(minutes=1),
        is_ai_generated=True, was_approved=True, sent_autonomously=True)          # the AI's own promise is not an answer
    assert collab_requests.pending(db, t.id, [conv.id], g.id).id == ask.id
    assert collab_requests.pending_for_inquiry(db, t.id, inq).id == ask.id
    other, _ = tenant(db)
    assert collab_requests.pending(db, other.id, [conv.id], g.id) is None
    msg(db, t.id, conv, "Hi, we'd love to host you. Here's how barter works...", inbound=False, ago=timedelta(days=1),
        sender_name="Asha")                                                       # a person replied
    assert collab_requests.pending(db, t.id, [conv.id], g.id) is None


# ── the lead autopilot ────────────────────────────────────────────────────────

def _decide(db, t, inq, **over):
    return rules.evaluate(db, t.id, inq, StageMap.load(db, t.id), settings(**over), now=NOW)


def test_a_waiting_collab_request_goes_to_the_collab_stage_not_lost(db):
    t, s = tenant(db)
    g, inq, conv = lead(db, t.id, s["general_enquiry"])
    msg(db, t.id, conv, "Hey!", ago=timedelta(days=19))
    msg(db, t.id, conv, "Can you give barter collaboration", ago=timedelta(days=12))
    msg(db, t.id, conv, "Our team will get back to you shortly.", inbound=False, ago=timedelta(days=11),
        is_ai_generated=True, was_approved=True, sent_autonomously=True)            # we spoke last, then 11 days of silence
    d = _decide(db, t, inq)
    assert d.to_stage.key == "collaboration_engagement" and d.rule == "collab_request" and d.lost_reason is None


def test_autopilot_applies_the_move_through_the_audited_path(db):
    t, s = tenant(db, mode="autopilot")
    g, inq, conv = lead(db, t.id, s["general_enquiry"])
    msg(db, t.id, conv, "Can you give barter collaboration", ago=timedelta(days=3))
    event = lead_autopilot_service.evaluate(db, t.id, inq.id, now=NOW)
    db.commit()
    assert event.status == "applied"
    db.refresh(inq)
    assert inq.stage_id == s["collaboration_engagement"].id
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead_autopilot.stage_moved").count() == 1


def test_never_auto_lost_while_a_collab_request_waits_even_without_a_collab_stage(db):
    t, s = tenant(db, mode="autopilot")
    s["collaboration_engagement"].is_collab_entry = False                         # a tenant with no collab stage
    db.commit()
    g, inq, conv = lead(db, t.id, s["active"], check_in="2026-10-01")           # dates passed: normally Lost
    msg(db, t.id, conv, "Can you give barter collaboration", ago=timedelta(days=3))
    event = lead_autopilot_service.evaluate(db, t.id, inq.id, now=NOW)
    db.commit()
    db.refresh(inq)
    assert inq.stage_id == s["active"].id
    assert event is None or event.status == "blocked"


# ── the reply task ────────────────────────────────────────────────────────────

T0 = datetime.now(timezone.utc) - timedelta(hours=2)


def _world(db, *, mode="autonomous", consults=True):
    cfg = {} if consults else {"agent_consult": {"enabled": False}}
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
               wa_ai_mode_default=mode, wa_ai_confidence_threshold=0.5, brand_config=cfg)
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Guest A", phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
              lead_identified_at=T0)
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True, ai_mode=mode)
    db.add(c)
    db.commit()
    return t, g, c


def _guest_says(db, t, c, body, _minutes):
    # Real time (the default), so each guest line comes after whatever the previous run stored or sent.
    m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="inbound", channel="whatsapp", body=body)
    db.add(m)
    db.commit()
    return m


class Scripted:
    def __call__(self, task):
        class _LLM:
            provider = "scripted"

            async def complete(self, **kwargs):
                if task == "quick_classify":
                    return {"tool_use": {"intent": "general"}}
                return {"tool_use": {"reply": "Thanks! Our team reviews every collaboration request and will reach out.",
                                     "confidence": 0.9, "citations": [], "needs_human": False}}
        return _LLM()


def _turn(db, t, c, m):
    sent = []
    with patch("app.workers.tasks.concierge_draft.get_llm", Scripted()), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), patch.object(db, "close"), \
         patch("app.services.push_service.send_to_tenant"), patch("app.workers.tasks.concierge_draft._emit_sse"), \
         patch("app.services.agent_consult_notify.emit_sse"), \
         patch("app.services.lead_alert_sender.deliver", return_value=False), \
         patch("app.workers.tasks.concierge_draft._send_whatsapp_typing_indicator"), \
         patch("app.services.agent_consult_service.queue_send", side_effect=lambda mid, *a, **k: sent.append(mid)), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay", side_effect=lambda **kw: sent.append(kw["message_id"])):
        concierge_draft.run(message_id=m.id, conversation_id=c.id, tenant_id=t.id)
    return [db.get(Message, i) for i in sent]


def _collab_tasks(db, t, c):
    return db.query(Task).filter(Task.tenant_id == t.id, Task.conversation_id == c.id,
                                 Task.title.like(collab_requests.TASK_PREFIX + "%")).all()


def test_autonomous_with_consults_one_holding_line_then_silence(db):
    t, g, c = _world(db)
    first = _turn(db, t, c, _guest_says(db, t, c, "Can you give barter collaboration", 0))
    consult = db.query(AgentConsult).filter_by(tenant_id=t.id, conversation_id=c.id).one()
    assert "collab_request" in consult.reason_codes and consult.status == "open"
    assert [m.sender_kind for m in first] == ["ai_holding"]                    # the AI's own promise is held, one honest line
    second = _turn(db, t, c, _guest_says(db, t, c, "Hloo any updates", 30))
    assert second == []                                                        # no new promise, no second holding line
    assert db.query(AgentConsult).filter_by(tenant_id=t.id, conversation_id=c.id).count() == 1
    assert _collab_tasks(db, t, c) == []                                       # the consult is the one work item


def test_draft_mode_raises_one_task_and_sends_nothing(db):
    t, g, c = _world(db, mode="shadow")
    assert _turn(db, t, c, _guest_says(db, t, c, "Can you give barter collaboration", 0)) == []
    assert _turn(db, t, c, _guest_says(db, t, c, "Hloo any updates", 30)) == []
    tasks = _collab_tasks(db, t, c)
    assert len(tasks) == 1 and tasks[0].inquiry_id is None and tasks[0].guest_id == g.id and not tasks[0].is_done


def test_consults_off_the_ai_promises_once_then_holds(db):
    t, g, c = _world(db, consults=False)
    first = _turn(db, t, c, _guest_says(db, t, c, "Can you give barter collaboration", 0))
    assert len(first) == 1 and first[0].is_ai_generated                       # the first reply goes out as before
    second = _turn(db, t, c, _guest_says(db, t, c, "Hloo any updates", 30))
    assert second == []                                                        # no second "the team will reach out"
    held = db.query(Message).filter_by(conversation_id=c.id, is_ai_generated=True, was_approved=None).one()
    assert "collaboration request" in held.ai_needs_human_reason
    assert len(_collab_tasks(db, t, c)) == 1


def test_ensure_task_is_once_per_conversation_and_per_tenant(db):
    t, g, c = _world(db, mode="shadow")
    ask = _guest_says(db, t, c, "Can you give barter collaboration", 0)
    assert collab_requests.ensure_task(db, t.id, c, g, ask) is not None
    assert collab_requests.ensure_task(db, t.id, c, g, ask) is None
    db.commit()
    other, og, oc = _world(db, mode="shadow")
    assert _collab_tasks(db, other, c) == [] and len(_collab_tasks(db, t, c)) == 1
