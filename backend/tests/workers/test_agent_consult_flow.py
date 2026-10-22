"""Ask a manager, end to end through the real concierge task with scripted model outputs.

A trigger means: the guessed answer is NOT sent (held as the consult's proposed answer), ONE holding reply goes out (never twice
in a row, never outside the 24 h window, never in draft mode), one open consult per conversation, the team is pushed.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.agent_consult import AgentConsult
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.workers.tasks.concierge_draft import concierge_draft
from tests.test_increment1_defect_specs import _tenant, _user


def setup_thread(db, body="Can I speak to a real person please?", *, mode="autonomous", channel=ChannelType.WHATSAPP,
                 phone=True, tenant=None, inbound_at=None):
    t = tenant or _tenant(db)
    t.wa_ai_mode_default = mode
    t.ig_ai_mode_default = mode
    t.wa_ai_confidence_threshold = 0.5
    t.ig_ai_confidence_threshold = 0.5
    db.commit()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Priya Sharma",
              phone=f"+9198456{uuid.uuid4().int % 100000:05d}" if phone else "",
              lead_identified_at=datetime.now(timezone.utc) if phone else None)
    db.add(g)
    db.commit()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=channel, is_open=True, ai_mode="shadow")
    db.add(c)
    db.commit()
    m = add_inbound(db, t, c, body, at=inbound_at)
    return t, g, c, m


def add_inbound(db, t, c, body, at=None):
    m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="inbound",
                channel=c.channel.value if hasattr(c.channel, "value") else c.channel, body=body)
    if at is not None:
        m.created_at = at
    db.add(m)
    db.commit()
    return m


class _Intent:
    def __init__(self, out):
        self.out = out

    async def complete(self, **kwargs):
        return {"tool_use": self.out}


class _Reply:
    def __init__(self, reply, confidence=0.95):
        self.reply, self.confidence = reply, confidence

    async def complete(self, **kwargs):
        return {"tool_use": {"reply": self.reply, "confidence": self.confidence, "citations": [], "needs_human": False}}


def run_turn(db, t, c, m, *, reply="Happy to help!", intent=None, confidence=0.95):
    sent = []

    def _get_llm(task):
        return _Intent(intent or {"intent": "general"}) if task == "quick_classify" else _Reply(reply, confidence)
    with patch("app.workers.tasks.concierge_draft.get_llm", _get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant") as push, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay", side_effect=lambda **kw: sent.append(kw["message_id"])), \
         patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay", side_effect=lambda **kw: sent.append(kw["message_id"])):
        concierge_draft.run(message_id=m.id, conversation_id=c.id, tenant_id=t.id)
    return sent, push


def _draft(db, c):
    return (db.query(Message).filter_by(conversation_id=c.id, direction="outbound", is_ai_generated=True)
            .order_by(Message.created_at.desc()).first())


def test_a_request_for_a_person_is_held_and_a_holding_reply_goes_once(db):
    t, g, c, m = setup_thread(db)
    mgr_id = _user(db, t.id, UserRole.MANAGER).id
    t_id, c_id = t.id, c.id
    sent, push = run_turn(db, t, c, m, reply="Sure! Our caravan has a lounge and a kitchenette.",
                          intent={"intent": "general", "wants_human": True})
    draft = _draft(db, c)
    assert draft.sent_autonomously is False and draft.was_approved is None       # the guess is not sent
    (consult,) = db.query(AgentConsult).filter_by(tenant_id=t.id).all()
    assert consult.status == "open" and "wants_human" in consult.reason_codes
    assert consult.question.startswith("Can I speak") and consult.proposed_answer == draft.body
    assert consult.level == "manager"                                             # nobody owns the lead: managers first
    hold = db.query(Message).filter_by(conversation_id=c.id, sender_kind="ai_holding").one()
    assert sent == [hold.id] and hold.sent_autonomously is True and hold.is_ai_generated is False
    assert any(call.kwargs.get("user_id") == mgr_id for call in push.call_args_list)

    # The guest writes again: the same consult grows, and no second holding reply in a row.
    t, c = db.get(Tenant, t_id), db.get(Conversation, c_id)
    m2 = add_inbound(db, t, c, "Hello?? anyone there")
    sent2, _ = run_turn(db, t, c, m2, reply="Yes!", intent={"intent": "general", "sentiment": "frustrated"})
    assert db.query(AgentConsult).filter_by(tenant_id=t_id).count() == 1
    consult = db.query(AgentConsult).filter_by(tenant_id=t_id).one()
    assert "frustrated" in consult.reason_codes and sent2 == []
    assert db.query(Message).filter_by(conversation_id=c_id, sender_kind="ai_holding").count() == 1


def test_an_ordinary_question_still_auto_sends(db):
    t, g, c, m = setup_thread(db, "What time can we leave Bengaluru?")
    sent, _ = run_turn(db, t, c, m, reply="Trips start from Bengaluru in the morning.", intent={"intent": "faq_answer"})
    assert _draft(db, c).sent_autonomously is True and sent == [_draft(db, c).id]
    assert db.query(AgentConsult).count() == 0


def test_draft_mode_never_opens_a_consult_or_sends_a_holding_reply(db):
    t, g, c, m = setup_thread(db, mode="shadow")
    sent, _ = run_turn(db, t, c, m, intent={"intent": "general", "wants_human": True})
    assert sent == [] and db.query(AgentConsult).count() == 0


def test_custom_route_discount_and_refund_are_consults(db):
    for body, code in (("Can you plan a custom route to Goa for us?", "custom_route"),
                       ("Any discount if we book two days?", "discount_request"),
                       ("I want a refund for last week's trip", "refund")):
        t, g, c, m = setup_thread(db, body)
        sent, _ = run_turn(db, t, c, m, reply="Sure, we can do that!")
        consult = db.query(AgentConsult).filter_by(tenant_id=t.id).one()
        assert code in consult.reason_codes, (body, consult.reason_codes)
        assert _draft(db, c).sent_autonomously is False


def test_outside_business_hours_the_holding_reply_names_the_morning(db):
    t, g, c, m = setup_thread(db)
    night = datetime(2026, 10, 22, 17, 30, tzinfo=timezone.utc)          # 23:00 IST
    with patch("app.services.agent_consult_settings.datetime") as dt, \
         patch("app.services.agent_consult_service._now", return_value=night):
        dt.now.return_value = night
        dt.side_effect = lambda *a, **k: datetime(*a, **k)
        run_turn(db, t, c, m, intent={"intent": "general", "wants_human": True})
    hold = db.query(Message).filter_by(conversation_id=c.id, sender_kind="ai_holding").one()
    assert "10 am tomorrow" in hold.body
    consult = db.query(AgentConsult).filter_by(tenant_id=t.id).one()
    due = consult.sla_due_at if consult.sla_due_at.tzinfo else consult.sla_due_at.replace(tzinfo=timezone.utc)
    assert due == datetime(2026, 10, 23, 4, 30, tzinfo=timezone.utc)      # 10:00 IST next morning


def test_no_holding_reply_once_the_window_closed(db):
    t, g, c, m = setup_thread(db, inbound_at=datetime.now(timezone.utc) - timedelta(hours=30))
    sent, _ = run_turn(db, t, c, m, intent={"intent": "general", "wants_human": True})
    consult = db.query(AgentConsult).filter_by(tenant_id=t.id).one()
    assert sent == [] and consult.holding_message_id is None
    assert consult.evidence["holding_not_sent"] == "24-hour window closed"


def test_consults_switched_off_keeps_the_old_behaviour(db):
    t, g, c, m = setup_thread(db, "What time can we leave?")
    t.brand_config = {"agent_consult": {"enabled": False}}
    db.commit()
    run_turn(db, t, c, m, intent={"intent": "general", "wants_human": True})
    assert db.query(AgentConsult).count() == 0


def test_consults_are_per_tenant(db):
    t1, _, c1, m1 = setup_thread(db)
    t2, _, c2, m2 = setup_thread(db, "What time can we leave?")
    ids = (t1.id, t2.id)
    run_turn(db, t1, c1, m1, intent={"intent": "general", "wants_human": True})
    t2, c2 = db.get(Tenant, ids[1]), db.get(Conversation, _conv_id(db, ids[1]))    # the task closed the session
    m2 = db.query(Message).filter_by(conversation_id=c2.id, direction="inbound").one()
    run_turn(db, t2, c2, m2, intent={"intent": "faq_answer"})
    assert db.query(AgentConsult).filter_by(tenant_id=ids[0]).count() == 1
    assert db.query(AgentConsult).filter_by(tenant_id=ids[1]).count() == 0


def _conv_id(db, tenant_id):
    return db.query(Conversation.id).filter_by(tenant_id=tenant_id).scalar()
