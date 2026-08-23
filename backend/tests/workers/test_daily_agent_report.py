"""Tests for the per-agent end-of-day report (agent-attribution
dashboard/reports plan) -- backend/app/workers/tasks/daily_agent_report.py."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.workers.tasks.daily_agent_report import send_daily_agent_report, daily_agent_report_all_tenants


@pytest.fixture(autouse=True)
def _no_postgres_lateral_join():
    with patch("app.services.message_metrics.chat_response_by_agent", return_value=[]):
        yield


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth", is_active=True)
    db.add(t); db.commit(); return t


def _make_user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent", email=None):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=email or f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.commit(); return u


class TestSendOneAgentReport:
    def test_sends_email_to_the_agent(self, db, monkeypatch):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, email="agent@test.com")
        monkeypatch.setattr("app.services.agent_analytics_service.generate_agent_narrative", lambda *a, **k: "")

        with patch("app.workers.tasks.daily_agent_report.SessionLocal", return_value=db), \
             patch("app.services.email_service._send", new_callable=AsyncMock, return_value=True) as mock_send:
            result = send_daily_agent_report.run(tenant.id, agent.id, day="2026-08-24")

        assert result.get("sent") is True
        mock_send.assert_awaited_once()
        sent_to = mock_send.call_args.args[0]
        assert sent_to == "agent@test.com"

    def test_to_email_override_wins(self, db, monkeypatch):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, email="agent@test.com")
        monkeypatch.setattr("app.services.agent_analytics_service.generate_agent_narrative", lambda *a, **k: "")

        with patch("app.workers.tasks.daily_agent_report.SessionLocal", return_value=db), \
             patch("app.services.email_service._send", new_callable=AsyncMock, return_value=True) as mock_send:
            send_daily_agent_report.run(tenant.id, agent.id, day="2026-08-24", to_email="test@override.com")

        assert mock_send.call_args.args[0] == "test@override.com"


class TestFanOut:
    def test_queues_one_send_per_eligible_agent(self, db, monkeypatch):
        tenant = _make_tenant(db)
        _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner", email="owner@test.com")
        _make_user(db, tenant.id, name="Agent1", email="a1@test.com")
        _make_user(db, tenant.id, name="Agent2", email="a2@test.com")

        monkeypatch.setattr("app.workers.tasks.daily_agent_report.settings.RESEND_API_KEY", "fake-key")
        with patch("app.workers.tasks.daily_agent_report.SessionLocal", return_value=db), \
             patch("app.workers.tasks.daily_agent_report.send_daily_agent_report.delay") as mock_delay:
            result = daily_agent_report_all_tenants.run()

        assert result["agents_queued"] == 2  # owner excluded
        assert mock_delay.call_count == 2

    def test_skips_loudly_with_no_email_key(self, db, monkeypatch):
        monkeypatch.setattr("app.workers.tasks.daily_agent_report.settings.RESEND_API_KEY", "")
        with patch("app.workers.tasks.daily_agent_report.SessionLocal", return_value=db):
            result = daily_agent_report_all_tenants.run()
        assert result["agents_queued"] == 0
