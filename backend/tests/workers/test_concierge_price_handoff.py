"""Price-handoff plan: a guest asking about cost gets a dedicated Task +
push alert so a human calls to discuss pricing -- without blocking the
AI's own (price-free) reply. Mirrors test_concierge_phone_decline_alert.py's
harness exactly.
"""
import uuid
from unittest.mock import patch

from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.task import Task
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import concierge_draft


def _setup(db, *, inbound_body):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        wa_ai_mode_default="autonomous", wa_ai_confidence_threshold=0.5,
    )
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Priya Sharma")
    db.add(guest); db.commit()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        channel=ChannelType.WHATSAPP, is_open=True, ai_mode="shadow",
    )
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="whatsapp", body=inbound_body,
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

        assert draft.sent_autonomously is True  # AI's own (price-free) reply still goes out

        task = db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).first()
        assert task is not None
        assert task.title == "Call lead about pricing — Priya Sharma"
        assert task.is_done is False
        # Real bug (Ratha, Sep 2026): with no due_date this Task never
        # appeared in My Day's "Due now" bucket, which hard-requires one.
        assert task.due_date is not None

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

        tasks = db.query(Task).filter_by(tenant_id=tenant_id, conversation_id=conv_id).all()
        assert len(tasks) == 1
