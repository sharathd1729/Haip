"""End-to-end: an autonomous send writes its audit row.

Covers the whole path through the real task rather than the service in
isolation -- the gap being closed was that concierge_draft dispatched the
send and simply never called record_outcome.
"""
import uuid
from unittest.mock import patch

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import concierge_draft


def _setup(db, *, autonomous: bool):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        wa_ai_mode_default="autonomous" if autonomous else "shadow",
        wa_ai_confidence_threshold=0.5,
    )
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Priya")
    db.add(guest); db.commit()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        channel=ChannelType.WHATSAPP, is_open=True, ai_mode="shadow",
    )
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="whatsapp",
        body="Hi, what time is check-in?",
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _FakeIntentLLM:
    async def complete(self, **kwargs):
        return {"tool_use": {"intent": "faq_answer"}}


def _reply_llm(reply="Check-in is from 2 PM, and check-out by 11."):
    class _Fake:
        async def complete(self, **kwargs):
            return {"tool_use": {"reply": reply, "confidence": 0.95,
                                 "citations": [], "needs_human": False}}
    return _Fake()


def _run(db, tenant, conv, inbound):
    def _fake_get_llm(task):
        return _FakeIntentLLM() if task == "quick_classify" else _reply_llm()
    with patch("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)


def test_autonomous_send_writes_outcome_row(db):
    tenant, guest, conv, inbound = _setup(db, autonomous=True)
    _run(db, tenant, conv, inbound)

    draft = (
        db.query(Message)
        .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
        .one()
    )
    assert draft.sent_autonomously is True

    row = db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).one()
    assert row.outcome == "sent_autonomous"
    assert row.actor_user_id is None
    assert row.intent == "faq_answer"


def test_shadow_draft_writes_no_outcome_row_until_a_human_acts(db):
    """A pending draft has no outcome yet -- the row is written on
    approve/reject, not on creation."""
    tenant, guest, conv, inbound = _setup(db, autonomous=False)
    _run(db, tenant, conv, inbound)

    draft = (
        db.query(Message)
        .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
        .one()
    )
    assert draft.sent_autonomously is False
    assert db.query(AIDraftOutcome).filter_by(draft_message_id=draft.id).count() == 0
    # Intent is still persisted, so the eventual approve/reject can use it.
    assert draft.ai_intent == "faq_answer"
