"""Tests for HAIP_AI_Autonomy_Plan.md Phase 1, ticket 4: the bounded
grounding loop + deterministic hallucination guard in concierge_draft.py.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType
from app.models.property import Property, RatePlan
from app.workers.tasks.concierge_draft import (
    concierge_draft, _check_grounding, _classify_and_extract, _ground_reply,
)


# ── _check_grounding: pure unit tests, no DB/mocking needed ────────────────

class TestCheckGrounding:
    def test_no_facts_no_claims_is_grounded(self):
        ok, reason = _check_grounding("Thanks for reaching out! How can I help?", [])
        assert ok is True
        assert reason is None

    def test_no_facts_but_price_mentioned_is_ungrounded(self):
        ok, reason = _check_grounding("The villa is ₹40,000 per night.", [])
        assert ok is False
        assert "grounded_facts" in reason

    def test_no_facts_but_availability_claim_is_ungrounded(self):
        ok, reason = _check_grounding("Yes, it's available on those dates!", [])
        assert ok is False

    def test_price_matching_grounded_fact_is_grounded(self):
        facts = [{"tool": "get_quote", "args": {}, "result": {"total": "22400"}}]
        ok, reason = _check_grounding("Your total comes to ₹22,400.", facts)
        assert ok is True
        assert reason is None

    def test_price_not_matching_any_grounded_fact_is_ungrounded(self):
        facts = [{"tool": "get_quote", "args": {}, "result": {"total": "22400"}}]
        ok, reason = _check_grounding("Your total comes to ₹99,999.", facts)
        assert ok is False
        assert "99,999" in reason or "99999" in reason

    def test_plain_reply_with_grounded_facts_present_is_fine(self):
        facts = [{"tool": "check_availability", "args": {}, "result": []}]
        ok, reason = _check_grounding("Let me know if you have other questions!", facts)
        assert ok is True


# ── _classify_and_extract / _ground_reply: mocked LLM + calculator_service ─

class TestGroundReply:
    @pytest.mark.asyncio
    async def test_general_intent_skips_grounding_entirely(self, monkeypatch):
        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM())

        with patch("app.services.calculator_service.calculator_service.search") as mock_search:
            intent, facts, actions = await _ground_reply(db=MagicMock(), tenant_id="t1", latest_message="Hi there!", inquiry=None)

        assert intent == "general"
        assert facts == []
        mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_availability_check_with_dates_calls_search(self, monkeypatch):
        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "intent": "availability_check",
                    "check_in": "2026-12-10", "check_out": "2026-12-12",
                    "adults": 2, "children": 0,
                }}

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM())

        fake_result = MagicMock(
            property_id="p1", property_name="Villa Test", available=True,
            price_per_night=10000, nights=2, currency="INR",
        )
        with patch("app.services.calculator_service.calculator_service.search", return_value=[fake_result]) as mock_search:
            intent, facts, actions = await _ground_reply(db=MagicMock(), tenant_id="t1", latest_message="Is the villa free Dec 10-12 for 2 adults?", inquiry=None)

        assert intent == "availability_check"
        assert mock_search.called
        assert len(facts) == 1
        assert facts[0]["tool"] == "check_availability"
        assert facts[0]["result"][0]["property_name"] == "Villa Test"

    @pytest.mark.asyncio
    async def test_price_quote_with_single_match_also_calls_build_quote(self, monkeypatch):
        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "intent": "price_quote",
                    "check_in": "2026-12-10", "check_out": "2026-12-12",
                    "adults": 2, "children": 0,
                }}

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM())

        fake_result = MagicMock(property_id="p1", property_name="Villa Test", available=True, price_per_night=10000, nights=2, currency="INR")
        fake_quote = MagicMock(subtotal=20000, gst=2400, total=22400, advance_amount=6720, currency="INR")

        with patch("app.services.calculator_service.calculator_service.search", return_value=[fake_result]), \
             patch("app.services.calculator_service.calculator_service.build_quote", return_value=fake_quote) as mock_quote:
            intent, facts, actions = await _ground_reply(db=MagicMock(), tenant_id="t1", latest_message="What would 2 nights cost?", inquiry=None)

        assert intent == "price_quote"
        assert mock_quote.called
        tools_called = [f["tool"] for f in facts]
        assert tools_called == ["check_availability", "get_quote"]
        # Ticket 4 (HAIP Inbox plan): a real quote was fetched, so a
        # send_quote suggested_action should be offered.
        assert len(actions) == 1
        assert actions[0]["action_type"] == "send_quote"
        assert actions[0]["action_config"]["property_id"] == "p1"

    @pytest.mark.asyncio
    async def test_grounded_intent_without_dates_returns_no_facts(self, monkeypatch):
        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "availability_check", "check_in": None, "check_out": None}}

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM())

        with patch("app.services.calculator_service.calculator_service.search") as mock_search:
            intent, facts, actions = await _ground_reply(db=MagicMock(), tenant_id="t1", latest_message="Do you have anything free?", inquiry=None)

        assert facts == []
        mock_search.assert_not_called()


# ── End-to-end: the Celery task itself ──────────────────────────────────────

def _setup_conversation(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500001", name="Priya")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True, ai_mode="shadow")
    db.add(conv); db.commit()
    inbound = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="whatsapp", body="Is the villa available Dec 10-12 for 2 adults?",
    )
    db.add(inbound); db.commit()
    return tenant, guest, conv, inbound


class TestConciergeDraftEndToEnd:
    def test_grounded_facts_persisted_on_draft_message(self, db, monkeypatch):
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "intent": "availability_check",
                    "check_in": "2026-12-10", "check_out": "2026-12-12", "adults": 2, "children": 0,
                }}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "reply": "Yes, the villa is available Dec 10-12! Let me know if you'd like a quote.",
                    "confidence": 0.9, "citations": [], "needs_human": False,
                }}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        fake_result = MagicMock(property_id="p1", property_name="Villa Test", available=True, price_per_night=10000, nights=2, currency="INR")
        with patch("app.services.calculator_service.calculator_service.search", return_value=[fake_result]), \
             patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .order_by(Message.created_at.desc())
            .first()
        )
        assert draft is not None
        assert draft.grounded_facts
        assert draft.grounded_facts[0]["tool"] == "check_availability"
        assert draft.was_approved is None  # shadow mode, awaiting approval
        assert float(draft.ai_confidence) == 0.9

    def test_ungrounded_price_claim_forces_needs_human(self, db, monkeypatch):
        """The hallucination guard: model cites a price with zero grounding
        (e.g. classify said 'general' so grounding never ran) -- must be
        caught and force needs_human regardless of the model's own
        self-reported confidence/needs_human."""
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                # Model hallucinates a specific price despite no grounding.
                return {"tool_use": {
                    "reply": "That villa is ₹55,000 per night and definitely available!",
                    "confidence": 0.95, "citations": [], "needs_human": False,
                }}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .order_by(Message.created_at.desc())
            .first()
        )
        assert draft is not None
        assert float(draft.ai_confidence) == 0.0  # forced by the guard, not the model's 0.95
        assert draft.was_approved is None  # never auto-sent

    def test_grounding_timeout_falls_back_gracefully(self, db, monkeypatch):
        """Never leave a guest unanswered because the loop hung -- a
        grounding-phase timeout must still produce a (ungrounded) draft."""
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _SlowIntentLLM:
            async def complete(self, **kwargs):
                import asyncio
                await asyncio.sleep(0.2)
                return {"tool_use": {"intent": "availability_check", "check_in": "2026-12-10", "check_out": "2026-12-12"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"reply": "Let me check and get back to you!", "confidence": 0.5, "citations": [], "needs_human": True}}

        def _fake_get_llm(task):
            return _SlowIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)
        monkeypatch.setattr("app.workers.tasks.concierge_draft.MAX_GROUNDING_SECONDS", 0.01)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .order_by(Message.created_at.desc())
            .first()
        )
        assert draft is not None  # a draft still got created despite the timeout
        assert not draft.grounded_facts
