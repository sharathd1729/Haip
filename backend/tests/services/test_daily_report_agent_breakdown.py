"""Tests for the owner report's per-agent section (agent-attribution
dashboard/reports plan): daily_report_service.get_agent_breakdown() and
its rendering in daily_report_email.render_daily_report()."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.call import Call, CallDisposition
from app.core.security import get_password_hash
from app.services import daily_report_service
from app.services.daily_report_email import render_daily_report


@pytest.fixture(autouse=True)
def _no_postgres_lateral_join():
    with patch("app.services.message_metrics.chat_response_by_agent", return_value=[]):
        yield


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit(); return t


def _make_user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=f"{uuid.uuid4().hex[:8]}@test.com", hashed_password=get_password_hash("pw"),
        role=role, is_active=True,
    )
    db.add(u); db.commit(); return u


class TestAgentBreakdown:
    def test_owner_and_manager_excluded_only_agents_included(self, db, monkeypatch):
        tenant = _make_tenant(db)
        _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent = _make_user(db, tenant.id, name="Agent")
        monkeypatch.setattr(
            "app.services.agent_analytics_service.generate_agent_narrative",
            lambda *a, **k: "Handled a steady day of leads.",
        )

        breakdown = daily_report_service.get_agent_breakdown(db, tenant.id, "2026-08-24")

        assert len(breakdown) == 1
        assert breakdown[0]["agent_name"] == "Agent"
        assert breakdown[0]["narrative"] == "Handled a steady day of leads."

    def test_includes_notable_calls_for_the_day(self, db, monkeypatch):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, name="Agent")
        monkeypatch.setattr(
            "app.services.agent_analytics_service.generate_agent_narrative",
            lambda *a, **k: "",
        )
        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=tenant.id, agent_id=agent.id,
            ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
            direction="outbound", from_number="+919000000001", to_number="+919000000002",
            ai_disposition=CallDisposition.HOT,
            ai_summary="Guest very interested in a Goa trip.", ai_score=90,
            created_at=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        ))
        db.commit()

        breakdown = daily_report_service.get_agent_breakdown(db, tenant.id, "2026-08-24")

        assert len(breakdown) == 1
        assert breakdown[0]["notable_calls"][0]["disposition"] == "hot"
        assert "Goa" in breakdown[0]["notable_calls"][0]["summary"]

    def test_one_agent_failing_does_not_break_the_rest(self, db, monkeypatch):
        tenant = _make_tenant(db)
        _make_user(db, tenant.id, name="Agent1")
        _make_user(db, tenant.id, name="Agent2")

        calls = {"n": 0}
        def _flaky_narrative(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return "ok"
        monkeypatch.setattr("app.services.agent_analytics_service.generate_agent_narrative", _flaky_narrative)

        breakdown = daily_report_service.get_agent_breakdown(db, tenant.id, "2026-08-24")

        assert len(breakdown) == 1  # the failing agent is skipped, not the whole report


class TestRenderWithByAgent:
    def test_render_does_not_crash_with_agent_section(self):
        report = {
            "kind": "morning",
            "date": "2026-08-24",
            "backlog_days": 5,
            "metrics": {
                "dms_in": 10, "replies_out": 8, "by_channel": {"whatsapp": 10},
                "new_leads": 3, "qualified_leads": 1, "shared_details": 2,
                "calls_total": 4, "calls_missed": 1, "missed_not_returned": 0,
                "awaiting_reply": 0,
            },
            "top_waiting": [],
            "insights": [],
            "by_agent": [{
                "agent_name": "Agent",
                "scorecard": {"leads_handled": 3, "calls_answered": 3, "calls_missed": 1, "ai_drafts_approved": 2, "ai_drafts_total": 3},
                "notable_calls": [{"disposition": "hot", "summary": "Guest interested in a Goa trip."}],
                "narrative": "Responded quickly and stayed on-topic across all conversations.",
            }],
        }
        html = render_daily_report(report, tenant_name="Ratha", dashboard_url="https://example.com")
        assert "Team performance" in html
        assert "Agent" in html
        assert "Goa" in html
