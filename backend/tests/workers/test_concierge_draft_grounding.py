"""Tests for HAIP_AI_Autonomy_Plan.md Phase 1, ticket 4: the bounded
grounding loop + deterministic hallucination guard in concierge_draft.py.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from datetime import date as _date, timedelta as _td

# Dates relative to today: the concierge refuses to check availability for dates that have already passed.
FUTURE_IN = (_date.today() + _td(days=60)).isoformat()
FUTURE_OUT_1 = (_date.today() + _td(days=61)).isoformat()
FUTURE_OUT = (_date.today() + _td(days=62)).isoformat()

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

    def test_addon_listing_available_with_no_date_context_is_grounded(self):
        """Confirmed live bug: 'Add-ons like BBQ, bonfire, or private chef
        available' has nothing to do with date/room availability -- it's a
        static KB menu listing -- but the bare-word regex flagged it as an
        ungrounded availability claim and zeroed confidence on every draft
        that mentioned an add-on, silently blocking autonomous send."""
        ok, reason = _check_grounding(
            "Hi Sharath, we can arrange a caravan to Goa with amenities like "
            "AC, kitchenette, and WiFi. Add-ons like BBQ, bonfire, or private "
            "chef available. Could you share your contact number and "
            "preferred travel dates?",
            [],
        )
        assert ok is True
        assert reason is None

    def test_availability_claim_in_own_sentence_still_caught_without_dates_word(self):
        """The stay-context gate isn't just the literal word 'dates' -- 'the
        caravan is available' should still be caught even if 'dates' itself
        is in a different sentence."""
        ok, reason = _check_grounding(
            "The caravan is available! When were you thinking of travelling?",
            [],
        )
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
                    "check_in": FUTURE_IN, "check_out": FUTURE_OUT,
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
                    "check_in": FUTURE_IN, "check_out": FUTURE_OUT,
                    "adults": 2, "children": 0,
                }}

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM())

        fake_result = MagicMock(property_id="p1", property_name="Villa Test", available=True, price_per_night=10000, nights=2, currency="INR", max_adults=4)
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
                    "check_in": FUTURE_IN, "check_out": FUTURE_OUT, "adults": 2, "children": 0,
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

        fake_result = MagicMock(property_id="p1", property_name="Villa Test", available=True, price_per_night=10000, nights=2, currency="INR", max_adults=4)
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
                return {"tool_use": {"intent": "availability_check", "check_in": FUTURE_IN, "check_out": FUTURE_OUT}}

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

    def test_completion_timeout_falls_back_gracefully(self, db, monkeypatch):
        """Confirmed live: a single concierge_draft run took 56.7s, almost
        entirely one adapters/llm/nvidia_nim.py chat/completions call with no
        timeout at all. A slow/hung final completion must still produce a
        safe, reviewable draft (needs_human, zero confidence) instead of
        leaving the guest with nothing and the task hanging indefinitely."""
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _SlowConciergeLLM:
            async def complete(self, **kwargs):
                import asyncio
                await asyncio.sleep(0.2)
                return {"tool_use": {"reply": "This should never be used.", "confidence": 0.95, "citations": [], "needs_human": False}}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _SlowConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)
        monkeypatch.setattr("app.workers.tasks.concierge_draft.MAX_REPLY_SECONDS_DEFAULT", 0.01)

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
        assert draft.body != "This should never be used."
        assert float(draft.ai_confidence) == 0.0
        assert draft.was_approved is None  # never auto-sent
        assert draft.ai_needs_human_reason == "AI reply generation timed out after 2 attempts"

    def test_completion_returns_but_empty_tool_use_falls_back_gracefully(self, db, monkeypatch):
        """Real bug, reported live: a blank "AI DRAFT 0%" sat in the inbox
        with nothing to approve/edit/reject. Root cause -- unlike the
        timeout path above, a completion that finishes normally but comes
        back with no usable tool_use (model declined the tool call, or
        returned a malformed/empty one) had no fallback: reply_text
        defaulted to "" and confidence to 0.0, producing an empty,
        unreviewable draft instead of a real holding reply."""
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _EmptyConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {}}  # model declined/malformed -- no "reply" key at all

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _EmptyConciergeLLM()

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
        assert draft.body  # never blank -- a real holding reply
        assert draft.body.strip() != ""
        assert float(draft.ai_confidence) == 0.0
        assert draft.was_approved is None  # never auto-sent
        assert draft.ai_needs_human_reason == "AI reply generation returned no usable content"

    def test_completion_call_caps_max_tokens(self, db, monkeypatch):
        """Confirmed live: one conversation's completion call never returned
        even with a 90s ceiling and no exception -- consistent with a
        degenerate generation loop against the shared adapter default of
        max_tokens=4096, sized for genuinely long tasks (report_gen/
        deep_reason), not a <45-word WhatsApp reply. Must be capped tightly
        here so a stuck generation can't run indefinitely regardless of
        what's happening inside the model."""
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        captured = {}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                captured.update(kwargs)
                return {"tool_use": {"reply": "Sure!", "confidence": 0.9, "citations": [], "needs_human": False}}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FakeConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        from app.workers.tasks.concierge_draft import REPLY_MAX_TOKENS
        assert captured.get("max_tokens") == REPLY_MAX_TOKENS
        assert REPLY_MAX_TOKENS < 4096  # meaningfully tighter than the adapter's shared default

    def test_completion_retry_recovers_from_a_transient_hang(self, db, monkeypatch):
        """Confirmed live: three real timeouts all landed within ~1s of
        whatever the bound was set to -- the signature of a request that
        genuinely hangs rather than one that's merely slow. A retry with a
        fresh request should recover when the first attempt was a one-off
        stall, instead of falling back to the generic apology every time."""
        tenant, guest, conv, inbound = _setup_conversation(db)

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        call_count = {"n": 0}

        class _FlakyConciergeLLM:
            async def complete(self, **kwargs):
                import asyncio
                call_count["n"] += 1
                if call_count["n"] == 1:
                    await asyncio.sleep(0.2)  # hangs past the per-attempt timeout
                return {"tool_use": {"reply": "The real answer.", "confidence": 0.9, "citations": [], "needs_human": False}}

        def _fake_get_llm(task):
            return _FakeIntentLLM() if task == "quick_classify" else _FlakyConciergeLLM()

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", _fake_get_llm)
        monkeypatch.setattr("app.workers.tasks.concierge_draft.MAX_REPLY_SECONDS_DEFAULT", 0.01)

        with patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db), \
             patch("app.services.push_service.send_to_tenant"):
            concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=tenant.id)

        assert call_count["n"] == 2  # first attempt hung, second was tried

        draft = (
            db.query(Message)
            .filter_by(conversation_id=conv.id, direction="outbound", is_ai_generated=True)
            .order_by(Message.created_at.desc())
            .first()
        )
        assert draft is not None
        assert draft.body == "The real answer."  # recovered, not the generic fallback
        assert float(draft.ai_confidence) == 0.9
