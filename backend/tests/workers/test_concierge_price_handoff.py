"""Price handoff. Since Ask a manager (22 Oct 2026) a LEAD's price question in handoff mode opens a consult instead of the old
"Call lead about pricing" task: the AI's draft is held (it becomes the proposed answer), the guest gets ONE holding reply and
a manager answers with the price. A qualified lead with no price question, or a guest without a phone, keeps the old path.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.agent_consult import AgentConsult
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.task import Task
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import concierge_draft


def _setup(db, *, inbound_body, phone=True, channel=ChannelType.WHATSAPP):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        wa_ai_mode_default="autonomous", wa_ai_confidence_threshold=0.5,
    )
    db.add(tenant); db.commit()
    # A lead (we hold their number) unless phone=False: the pricing callback needs a number to call.
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Priya Sharma",
                  phone="+919845612345" if phone else "", lead_identified_at=datetime.now(timezone.utc) if phone else None)
    db.add(guest); db.commit()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        channel=channel, is_open=True, ai_mode="shadow",
    )
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel=channel.value, body=inbound_body,
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _FakeIntentLLM:
    def __init__(self, intent="general"):
        self.intent = intent

    async def complete(self, **kwargs):
        return {"tool_use": {"intent": self.intent}}


class _FakeConciergeLLM:
    def __init__(self, reply, confidence=0.95):
        self.reply, self.confidence = reply, confidence

    async def complete(self, **kwargs):
        return {"tool_use": {"reply": self.reply, "confidence": self.confidence, "citations": [], "needs_human": False}}


def _run(db, tenant_id, conv_id, message_id, reply_adapter, intent="general"):
    def _fake_get_llm(task):
        return _FakeIntentLLM(intent) if task == "quick_classify" else reply_adapter
    with patch("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        concierge_draft.run(message_id=message_id, conversation_id=conv_id, tenant_id=tenant_id)
    return (
        db.query(Message)
        .filter_by(conversation_id=conv_id, direction="outbound", is_ai_generated=True)
        .order_by(Message.created_at.desc())
        .first()
    )


class TestPriceHandoff:
    def test_price_quote_intent_creates_a_task_with_a_due_date(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="What's the price for a weekend trip?")
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id
        adapter = _FakeConciergeLLM("Our team will personally work out the best option and pricing for you.")
        draft = _run(db, tenant_id, conv_id, message_id, adapter, intent="price_quote")

        assert draft.sent_autonomously is False and draft.was_approved is None       # held: a manager answers with the price
        (consult,) = db.query(AgentConsult).filter_by(tenant_id=tenant_id, conversation_id=conv_id).all()
        assert consult.status == "open" and "price_handoff" in consult.reason_codes
        assert consult.proposed_answer == draft.body and consult.draft_message_id == draft.id
        assert consult.sla_due_at is not None
        hold = db.query(Message).filter_by(conversation_id=conv_id, sender_kind="ai_holding").one()
        assert "our team" in hold.body.lower() or "team" in hold.body.lower()
        # The consult replaces the old pricing task (no second work item for the same question).
        assert db.query(Task).filter(Task.tenant_id == tenant_id, Task.title.like("Call lead about pricing%")).count() == 0

    def test_no_task_for_an_ordinary_message(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="Is the caravan available this weekend?")
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id
        adapter = _FakeConciergeLLM("Let me check our availability for you.")
        _run(db, tenant_id, conv_id, message_id, adapter, intent="availability_check")

        assert db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).first() is None

    def test_deduplicates_on_repeated_price_question(self, db):
        tenant, guest, conv, inbound1 = _setup(db, inbound_body="How much does it cost?")
        tenant_id, conv_id, message_id_1 = tenant.id, conv.id, inbound1.id
        adapter = _FakeConciergeLLM("Our team will personally share pricing with you.")
        _run(db, tenant_id, conv_id, message_id_1, adapter, intent="price_quote")

        inbound2 = Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id,
            direction="inbound", channel="whatsapp", body="Seriously what's the rate",
        )
        db.add(inbound2); db.commit()
        _run(db, tenant_id, conv_id, inbound2.id, adapter, intent="price_quote")

        # One open consult per conversation; the second price question appends to it, and the holding reply is not repeated.
        assert db.query(AgentConsult).filter_by(tenant_id=tenant_id, conversation_id=conv_id).count() == 1
        assert db.query(Message).filter_by(conversation_id=conv_id, sender_kind="ai_holding").count() == 1

    def test_no_task_for_a_guest_with_no_phone_number(self, db):
        """An Instagram DM asking the price is not a lead yet: no "Call lead about pricing" task (there is no number to call);
        the reply itself still goes out and asks for the number. Other workspaces are untouched."""
        tenant, guest, conv, inbound = _setup(db, inbound_body="How much for 2 nights?", phone=False, channel=ChannelType.INSTAGRAM)
        tenant_id, conv_id, message_id = tenant.id, conv.id, inbound.id
        other, _, other_conv, other_in = _setup(db, inbound_body="What's the price?")
        other_id, other_conv_id, other_msg_id = other.id, other_conv.id, other_in.id
        adapter = _FakeConciergeLLM("Our team will share pricing personally. Could you share a number to reach you on?")
        with patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay"):
            _run(db, tenant_id, conv_id, message_id, adapter, intent="price_quote")
        assert db.query(Task).filter(Task.tenant_id == tenant_id, Task.title.like("Call lead about pricing%")).count() == 0

        assert db.query(AgentConsult).filter_by(tenant_id=tenant_id).count() == 0          # no number: the reply asks for it

        _run(db, other_id, other_conv_id, other_msg_id, adapter, intent="price_quote")
        assert db.query(AgentConsult).filter_by(tenant_id=other_id).count() == 1
        assert db.query(AgentConsult).filter_by(tenant_id=tenant_id).count() == 0
        assert db.query(Task).filter(Task.tenant_id == tenant_id, Task.title.like("Call lead about pricing%")).count() == 0
