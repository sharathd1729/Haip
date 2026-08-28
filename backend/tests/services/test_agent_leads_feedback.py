"""Detailed per-lead report: generate_leads_summary_and_feedback.

Aggregate leads-summary paragraph + coaching feedback over an agent's
already-fetched lead cards -- distinct from generate_agent_narrative
(scorecard-based) and from each lead's own ai_lead_analysis.
"""
import json
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.agent_analytics_service import generate_leads_summary_and_feedback


def _tenant_and_agent(db):
    t = Tenant(id=str(uuid.uuid4()), name="Rathaa", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    agent = User(id=str(uuid.uuid4()), tenant_id=t.id, email="krisha@t.com", name="Krisha", role=UserRole.RESERVATIONS)
    db.add(agent); db.commit()
    return t.id, agent.id


def _fake_adapter(summary: str, feedback: list | None = None):
    payload = {"summary": summary, "feedback": feedback or []}

    class _Fake:
        async def complete(self, **kwargs):
            return {"content": json.dumps(payload), "model": "test-model"}
    return _Fake()


_SAMPLE_LEADS = [
    {"guest_name": "Ritik", "channel": "instagram", "status": "booked", "intent": "anniversary weekend",
     "route_mentioned": "Bangalore -> Nandi Hills", "quoted_amount": 42000,
     "upsell_offered": "sunset add-on", "upsell_accepted": True,
     "ai_lead_analysis": "Fast-moving, high-intent guest."},
    {"guest_name": "Deepa", "channel": "call", "status": "lost", "intent": "family trip",
     "route_mentioned": "Bangalore -> Coorg", "quoted_amount": 25000,
     "upsell_offered": None, "upsell_accepted": None,
     "ai_lead_analysis": "Objected to the day-rate immediately."},
]


class TestHappyPath:
    def test_returns_summary_and_feedback(self, db):
        tenant_id, agent_id = _tenant_and_agent(db)
        adapter = _fake_adapter(
            "One booking with an accepted upsell, one price objection.",
            [{"type": "good", "text": "Ritik's upsell landed because it was offered mid-conversation."},
             {"type": "improve", "text": "Quote Deepa's day-rate earlier next time."}],
        )
        with patch("app.adapters.llm.get_llm", return_value=adapter):
            result = generate_leads_summary_and_feedback(db, tenant_id, agent_id, _SAMPLE_LEADS)

        assert result is not None
        assert "booking" in result["summary"]
        assert result["feedback"][0]["type"] == "good"
        assert result["feedback"][1]["type"] == "improve"


class TestEmptyInput:
    def test_no_leads_returns_none_without_calling_the_llm(self, db):
        tenant_id, agent_id = _tenant_and_agent(db)
        with patch("app.adapters.llm.get_llm") as mock_get_llm:
            result = generate_leads_summary_and_feedback(db, tenant_id, agent_id, [])

        mock_get_llm.assert_not_called()
        assert result is None


class TestMalformedOutput:
    def test_unparseable_response_returns_none(self, db):
        tenant_id, agent_id = _tenant_and_agent(db)

        class _Broken:
            async def complete(self, **kwargs):
                return {"content": "not json", "model": "test-model"}

        with patch("app.adapters.llm.get_llm", return_value=_Broken()):
            result = generate_leads_summary_and_feedback(db, tenant_id, agent_id, _SAMPLE_LEADS)

        assert result is None

    def test_at_most_two_feedback_items_kept(self, db):
        tenant_id, agent_id = _tenant_and_agent(db)
        adapter = _fake_adapter("Summary.", [
            {"type": "good", "text": "A"}, {"type": "improve", "text": "B"}, {"type": "good", "text": "C"},
        ])
        with patch("app.adapters.llm.get_llm", return_value=adapter):
            result = generate_leads_summary_and_feedback(db, tenant_id, agent_id, _SAMPLE_LEADS)

        assert len(result["feedback"]) == 2


class TestUnknownAgent:
    def test_missing_agent_returns_none(self, db):
        tenant_id, _ = _tenant_and_agent(db)
        result = generate_leads_summary_and_feedback(db, tenant_id, str(uuid.uuid4()), _SAMPLE_LEADS)
        assert result is None
