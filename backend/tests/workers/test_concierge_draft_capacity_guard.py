"""Tests for the capacity hallucination guard (concierge_reply v9).

Confirmed live: a guest asking about a 20-person group was told "designed
for up to 4 guests" -- the real max_adults is 8, and nothing in the prompt
ever rendered a capacity figure at all, so the model invented one outright.
_check_grounding() now treats a capacity claim ("up to N guests", "sleeps
N", "fits N pax") the same way it already treats a price claim: it must
trace back to a real number in grounded_facts, or the draft is forced to
needs_human/confidence=0.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.property import Property
from app.models.conversation import Conversation, Message, ChannelType
from app.workers.tasks.concierge_draft import (
    concierge_draft, _check_grounding, _max_known_capacity, _ground_reply,
)


class TestCheckGroundingCapacity:
    def test_capacity_claim_matching_known_value_is_grounded(self):
        facts = [{"tool": "check_availability", "args": {}, "result": [
            {"property_id": "p1", "max_adults": 8, "available": True},
        ]}]
        ok, reason = _check_grounding("We can host up to 8 guests per caravan.", facts)
        assert ok is True
        assert reason is None

    def test_capacity_claim_not_matching_any_known_value_is_ungrounded(self):
        facts = [{"tool": "check_availability", "args": {}, "result": [
            {"property_id": "p1", "max_adults": 8, "available": True},
        ]}]
        ok, reason = _check_grounding("Our caravans are designed for up to 4 guests.", facts)
        assert ok is False
        assert "4" in reason

    def test_capacity_claim_with_zero_grounding_is_ungrounded(self):
        ok, reason = _check_grounding("Our caravans are designed for up to 4 guests.", [])
        assert ok is False

    def test_capacity_claim_matches_max_capacity_note(self):
        facts = [{"tool": "check_availability", "args": {}, "result": [], "max_capacity_note": 8}]
        ok, reason = _check_grounding("Max capacity is 8 guests per caravan.", facts)
        assert ok is True

    def test_non_capacity_reply_unaffected(self):
        ok, reason = _check_grounding("Thanks for reaching out! How can I help?", [])
        assert ok is True


class TestMaxKnownCapacity:
    def test_returns_max_across_active_properties(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        db.add(Property(id=str(uuid.uuid4()), tenant_id=tenant.id, name="White Caravan", slug="wc", type="caravan", max_adults=8, is_active=True))
        db.add(Property(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Black Caravan", slug="bc", type="caravan", max_adults=8, is_active=True))
        db.commit()

        assert _max_known_capacity(db, tenant.id, None) == 8

    def test_returns_none_when_no_active_properties(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()

        assert _max_known_capacity(db, tenant.id, None) is None


class TestGroundReplyCapacityNote:
    @pytest.mark.asyncio
    async def test_empty_results_over_capacity_includes_note(self, db, monkeypatch):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        db.add(Property(id=str(uuid.uuid4()), tenant_id=tenant.id, name="White Caravan", slug="wc", type="caravan", max_adults=8, is_active=True))
        db.commit()

        class _FakeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "intent": "availability_check",
                    "check_in": "2026-12-10", "check_out": "2026-12-11",
                    "adults": 20, "children": 0,
                }}

        monkeypatch.setattr("app.workers.tasks.concierge_draft.get_llm", lambda task: _FakeLLM())

        with patch("app.services.calculator_service.calculator_service.search", return_value=[]):
            intent, facts, actions = await _ground_reply(db=db, tenant_id=tenant.id, latest_message="20 guests for Dec 10-11?", inquiry=None)

        assert facts[0]["max_capacity_note"] == 8


class TestConciergeDraftEndToEndCapacityGuard:
    def test_hallucinated_capacity_forces_needs_human(self, db, monkeypatch):
        """The model states a capacity figure with zero grounding for it
        (classify said 'general' so grounding never ran) -- must be caught
        regardless of the model's own self-reported confidence."""
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500009", name="Priya")
        db.add(guest); db.commit()
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True, ai_mode="shadow")
        db.add(conv); db.commit()
        inbound = Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction="inbound", channel="whatsapp", body="We're a group of 20, can you take us?")
        db.add(inbound); db.commit()

        class _FakeIntentLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {"intent": "general"}}

        class _FakeConciergeLLM:
            async def complete(self, **kwargs):
                return {"tool_use": {
                    "reply": "Our caravans are designed for up to 4 guests, but we can arrange more for larger groups!",
                    "confidence": 0.9, "citations": [], "needs_human": False,
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
        assert float(draft.ai_confidence) == 0.0  # forced by the guard, not the model's 0.9
        assert draft.was_approved is None  # never auto-sent
