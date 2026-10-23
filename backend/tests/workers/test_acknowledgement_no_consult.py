"""A bare acknowledgement ("Okay", "thanks", "👍", "okay waiting to hear from you") is never a repeated question, never opens
an "Ask a manager" consult, and gets no reply when our last message asked nothing.

Live bug (Rathaa, Oct 2026, synthetic copy of the thread): after several "any updates?" turns the AI had answered with the same
intent, the guest wrote "Okay"; a consult opened at manager level labelled "The guest asked the same thing again".
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.agent_consult import AgentConsult
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import agent_escalation_rules as r
from app.workers.tasks.concierge_draft import _closing_acknowledgement, concierge_draft


@pytest.mark.parametrize("text", ["Okay", "ok", "OK.", "okk", "thanks", "Thank you so much", "👍", "🙏🙏", "sure",
                                  "Okay waiting to hear from you", "noted", "got it, thanks", "ok will wait", "Okay\nThanks"])
def test_acknowledgements(text):
    assert r.is_acknowledgement(text)


@pytest.mark.parametrize("text", ["", "Hloo any updates!?", "Do you know when they will let me know", "ok, cancel it",
                                  "Okay, what about pets?", "Can you give barter collaboration", "yes", "Hi",
                                  "ok we are 4 adults for next weekend"])
def test_not_acknowledgements(text):
    assert not r.is_acknowledgement(text)


def _history(n_same_intent=2):
    """The live shape: guest follow-ups the AI answered with the same intent, all sent, no person in between."""
    h = []
    for q, a in (("Hloo any updates!?", "Our team will get back to you shortly."),
                 ("Do you know when they will let me know", "Our team will get back to you shortly."))[:n_same_intent]:
        h += [{"direction": "inbound", "body": q, "ai": False, "sent": False, "intent": None, "human": False},
              {"direction": "outbound", "body": a, "ai": True, "sent": True, "intent": "booking_status", "human": False}]
    h.append({"direction": "inbound", "body": "Okay waiting to hear from you", "ai": False, "sent": False, "intent": None,
              "human": False})
    h.append({"direction": "outbound", "body": "We'll get back to you as soon as possible.", "ai": True, "sent": True,
              "intent": "booking_status", "human": False})
    return h


def test_an_acknowledgement_is_never_a_repeated_question():
    v = r.evaluate(r.TurnSignals(burst_text="Okay", intent="booking_status", confidence=0.9, history=_history(),
                                 reply_text="Our team is finalising this and will share it shortly."))
    assert "repeat_question" not in v.reasons and "unanswered_questions" not in v.reasons
    # The same history with a real repeated question still asks a person (the rule itself is unchanged).
    again = r.evaluate(r.TurnSignals(burst_text="Do you know when they will let me know", intent="booking_status",
                                     confidence=0.9, history=_history(), reply_text="Soon."))
    assert "repeat_question" in again.reasons


# ── through the real reply task ──────────────────────────────────────────────

T0 = datetime.now(timezone.utc) - timedelta(hours=3)


def _world(db, last_ours: str):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
               wa_ai_mode_default="autonomous", wa_ai_confidence_threshold=0.5, brand_config={})
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Guest A", phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
              lead_identified_at=T0)
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                     ai_mode="autonomous")
    db.add(c)
    db.flush()
    turns = [("inbound", "Hloo any updates!?"), ("outbound", "Our team will get back to you shortly."),
             ("inbound", "Do you know when they will let me know"), ("outbound", "Our team will get back to you shortly."),
             ("inbound", "Okay waiting to hear from you"), ("outbound", last_ours), ("inbound", "Okay")]
    msgs = []
    for i, (d, body) in enumerate(turns):
        kw = dict(is_ai_generated=True, was_approved=True, sent_autonomously=True, ai_intent="booking_status") if d == "outbound" else {}
        m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=d, channel="whatsapp", body=body,
                    created_at=T0 + timedelta(minutes=10 * i), **kw)
        db.add(m)
        msgs.append(m)
    db.commit()
    return t, c, msgs[-1]


class Scripted:
    def __init__(self):
        self.calls = []

    def __call__(self, task):
        outer = self

        class _LLM:
            provider = "scripted"

            async def complete(self, **kwargs):
                outer.calls.append(task)
                if task == "quick_classify":
                    return {"tool_use": {"intent": "booking_status"}}
                return {"tool_use": {"reply": "Great, I'll check the weekend for you now.", "confidence": 0.9,
                                     "citations": [], "needs_human": False}}
        return _LLM()


def _run(db, tenant_id, conv_id, msg_id):
    llm, sent = Scripted(), []
    with patch("app.workers.tasks.concierge_draft.get_llm", llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), patch.object(db, "close"), \
         patch("app.services.push_service.send_to_tenant"), patch("app.workers.tasks.concierge_draft._emit_sse"), \
         patch("app.services.agent_consult_notify.emit_sse"), \
         patch("app.services.lead_alert_sender.deliver", return_value=False), \
         patch("app.workers.tasks.concierge_draft._send_whatsapp_typing_indicator") as typing, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay", side_effect=lambda **kw: sent.append(kw["message_id"])):
        concierge_draft.run(message_id=msg_id, conversation_id=conv_id, tenant_id=tenant_id)
    return llm, sent, typing


def test_a_bare_okay_after_a_holding_line_gets_nothing(db):
    t, c, okay = _world(db, "We'll get back to you as soon as possible.")
    assert _closing_acknowledgement(db, t.id, c.id)
    llm, sent, typing = _run(db, t.id, c.id, okay.id)
    assert llm.calls == [] and sent == [] and not typing.called          # no model call, no "typing...", nothing sent
    assert db.query(AgentConsult).filter_by(tenant_id=t.id, conversation_id=c.id).count() == 0
    assert db.query(Message).filter(Message.conversation_id == c.id, Message.created_at > okay.created_at).count() == 0


def test_okay_answering_our_question_is_drafted_and_opens_no_consult(db):
    t, c, okay = _world(db, "Shall I check the long weekend for you?")
    assert not _closing_acknowledgement(db, t.id, c.id)
    llm, sent, _ = _run(db, t.id, c.id, okay.id)
    assert "concierge_draft" in llm.calls                                # it is an answer: the AI replies
    assert db.query(AgentConsult).filter_by(tenant_id=t.id, conversation_id=c.id).count() == 0   # third same-intent turn
    assert len(sent) == 1


def test_another_tenants_conversation_is_left_alone(db):
    t, c, okay = _world(db, "We'll get back to you as soon as possible.")
    other, _, _ = _world(db, "Anything else?")
    assert not _closing_acknowledgement(db, other.id, c.id)
    llm, sent, _ = _run(db, other.id, c.id, okay.id)
    assert llm.calls == [] and sent == []
