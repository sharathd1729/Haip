"""Auto-send soft-escalation drafts, flag the lead for follow-up plan:
concierge_draft.py used to conflate two different signals into one
`needs_human` flag -- the model's own soft "a human should ideally own
this" judgment (confident, safe draft, just not a fully automatable
outcome) and the draft actually being wrong or risky (hallucination,
price leak, refund/legal/safety escalation keyword, rate limiting). Both
blocked autonomous sending identically. Diagnosed live on `rathaa`: a
90%-confidence, genuinely-autonomous-mode draft for a guest asking about a
custom 20-person route never sent, because the model's own soft
self-report was treated the same as a hard safety violation.

Fix: a new `hard_block` flag, set only by the three deterministic guards
(grounding, escalation, price-leak) plus the rate limiter -- `needs_human`
itself is unchanged everywhere else (still persisted to
`ai_needs_human_reason`, still read by the phone-nudge suggestion). Only
`hard_block` gates `should_auto_send`.

These tests mirror test_concierge_autonomous_audit.py's harness exactly.
"""
import uuid
from unittest.mock import patch

from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks.concierge_draft import concierge_draft


def _setup(db, *, inbound_body="Hi, what time is check-in?", threshold=0.5):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth",
        wa_ai_mode_default="autonomous",
        wa_ai_confidence_threshold=threshold,
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
        direction="inbound", channel="whatsapp", body=inbound_body,
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class _FakeIntentLLM:
    async def complete(self, **kwargs):
        return {"tool_use": {"intent": "faq_answer"}}


def _reply_llm(reply, confidence, needs_human, reason_needs_human=None):
    class _Fake:
        async def complete(self, **kwargs):
            return {"tool_use": {
                "reply": reply, "confidence": confidence, "citations": [],
                "needs_human": needs_human, "reason_needs_human": reason_needs_human,
            }}
    return _Fake()


def _run(db, tenant, conv, inbound, reply_adapter, rate_limit_allowed=True):
    def _fake_get_llm(task):
        return _FakeIntentLLM() if task == "quick_classify" else reply_adapter
    with patch("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
         patch("app.services.push_service.send_to_tenant"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"), \
         patch(
             "app.services.ai_rate_limit_service.check_send_allowed",
             return_value=(rate_limit_allowed, None if rate_limit_allowed else "hourly cap reached"),
         ):
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)
    return (
        db.query(Message)
        .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
        .one()
    )


class TestSoftEscalationAutoSends:
    def test_soft_needs_human_still_auto_sends_and_flags_reason(self, db):
        """The model's own soft needs_human is still not a trigger by itself (Ask a manager rules are code, never the model)."""
        tenant, guest, conv, inbound = _setup(
            db, inbound_body="We're a group of 20 wanting a weekend trip through Coorg."
        )
        reply = "That sounds like a great trip! I've noted your group size for our team to help plan the perfect route."
        adapter = _reply_llm(
            reply, confidence=0.9, needs_human=True,
            reason_needs_human="Guest wants a custom 20-person route -- needs personal planning.",
        )
        draft = _run(db, tenant, conv, inbound, adapter)

        assert draft.sent_autonomously is True
        assert draft.was_approved is True
        assert draft.ai_needs_human_reason == "Guest wants a custom 20-person route -- needs personal planning."


class TestHardBlocksStillBlock:
    def test_ungrounded_capacity_claim_still_blocks(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="Can it fit 4 people?")
        # No grounded_facts exist for this conversation -- a specific
        # capacity number in the reply is an ungrounded claim regardless of
        # the model's own confidence/needs_human.
        adapter = _reply_llm(
            "Our caravan fits up to 4 guests comfortably.",
            confidence=0.95, needs_human=False,
        )
        draft = _run(db, tenant, conv, inbound, adapter)

        assert draft.sent_autonomously is False
        assert draft.was_approved is None
        assert "ungrounded claim" in (draft.ai_needs_human_reason or "")

    def test_escalation_keyword_still_blocks(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="I want a refund for my booking.")
        adapter = _reply_llm(
            "I understand your concern, let me help.",
            confidence=0.95, needs_human=False,
        )
        draft = _run(db, tenant, conv, inbound, adapter)

        assert draft.sent_autonomously is False
        assert draft.was_approved is None
        assert "escalation" in (draft.ai_needs_human_reason or "")

    def test_price_leak_still_blocks(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="How much for 2 nights?")
        adapter = _reply_llm(
            "That will be ₹25000 for the package.",
            confidence=0.95, needs_human=False,
        )
        draft = _run(db, tenant, conv, inbound, adapter)

        assert draft.sent_autonomously is False
        assert draft.was_approved is None
        assert "price leak" in (draft.ai_needs_human_reason or "")

    def test_rate_limit_still_overrides_a_would_be_soft_escalate_send(self, db):
        tenant, guest, conv, inbound = _setup(db, inbound_body="Hi, what time is check-in?")
        adapter = _reply_llm(
            "Check-in is from 2 PM, and check-out by 11.",
            confidence=0.95, needs_human=False,
        )
        draft = _run(db, tenant, conv, inbound, adapter, rate_limit_allowed=False)

        assert draft.sent_autonomously is False
        assert draft.was_approved is None
        assert "rate limited" in (draft.ai_needs_human_reason or "")
