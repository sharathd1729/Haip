"""Tests for the per-agent pending-leads worklist reminder email --
backend/app/workers/tasks/agent_worklist_email.py. Mirrors
test_daily_agent_report.py's fixtures/shape; the send-vs-skip behaviour
(only send when there's something pending) is the one thing genuinely new
here versus that file's always-sends-if-there's-any-day-data report.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType
from app.core.security import get_password_hash
from app.workers.tasks.agent_worklist_email import (
    send_agent_worklist_email, agent_worklist_email_all_tenants,
)


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


def _make_pending_lead(db, tenant, agent):
    """One conversation, assigned to `agent`, with an unanswered inbound
    message -- the simplest row that makes worklist_service.awaiting_reply()
    (and therefore build_worklist()'s total pending count) non-zero."""
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+919876500099", name="Pending Guest")
    db.add(guest); db.commit()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        channel=ChannelType.WHATSAPP, is_open=True, assigned_to=agent.id,
    )
    db.add(conv); db.commit()
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
        direction="inbound", channel="whatsapp", body="Are you available this weekend?",
    )
    db.add(msg); db.commit()
    return conv


class TestSendOneAgentWorklistEmail:
    def test_sends_email_when_agent_has_pending_leads(self, db):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, email="agent@test.com")
        _make_pending_lead(db, tenant, agent)

        with patch("app.workers.tasks.agent_worklist_email.SessionLocal", return_value=db), \
             patch("app.services.email_service._send", new_callable=AsyncMock, return_value=True) as mock_send:
            result = send_agent_worklist_email.run(tenant.id, agent.id, "morning")

        assert result["sent"] is True
        assert result["pending"] == 1
        mock_send.assert_awaited_once()
        assert mock_send.call_args.args[0] == "agent@test.com"

    def test_skips_send_when_nothing_pending(self, db):
        """The one thing genuinely different from daily_agent_report.py:
        this is a 3x/day reminder, so an agent with a clean worklist must
        not get three "all clear" emails every day."""
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, email="agent@test.com")

        with patch("app.workers.tasks.agent_worklist_email.SessionLocal", return_value=db), \
             patch("app.services.email_service._send", new_callable=AsyncMock, return_value=True) as mock_send:
            result = send_agent_worklist_email.run(tenant.id, agent.id, "afternoon")

        assert result["status"] == "nothing_pending"
        mock_send.assert_not_awaited()

    def test_to_email_override_wins(self, db):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, email="agent@test.com")
        _make_pending_lead(db, tenant, agent)

        with patch("app.workers.tasks.agent_worklist_email.SessionLocal", return_value=db), \
             patch("app.services.email_service._send", new_callable=AsyncMock, return_value=True) as mock_send:
            send_agent_worklist_email.run(tenant.id, agent.id, "evening", to_email="test@override.com")

        assert mock_send.call_args.args[0] == "test@override.com"

    def test_only_counts_leads_assigned_to_this_agent(self, db):
        """A pending lead assigned to a different agent must not trigger a
        send or appear in this agent's email -- worklist_service's own
        scope_user_id filter, exercised end to end here."""
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, email="agent@test.com")
        other_agent = _make_user(db, tenant.id, email="other@test.com")
        _make_pending_lead(db, tenant, other_agent)

        with patch("app.workers.tasks.agent_worklist_email.SessionLocal", return_value=db), \
             patch("app.services.email_service._send", new_callable=AsyncMock, return_value=True) as mock_send:
            result = send_agent_worklist_email.run(tenant.id, agent.id, "morning")

        assert result["status"] == "nothing_pending"
        mock_send.assert_not_awaited()


class TestFanOut:
    def test_queues_one_send_per_eligible_agent(self, db, monkeypatch):
        tenant = _make_tenant(db)
        _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner", email="owner@test.com")
        _make_user(db, tenant.id, name="Agent1", email="a1@test.com")
        _make_user(db, tenant.id, name="Agent2", email="a2@test.com")

        monkeypatch.setattr("app.workers.tasks.agent_worklist_email.settings.RESEND_API_KEY", "fake-key")
        with patch("app.workers.tasks.agent_worklist_email.SessionLocal", return_value=db), \
             patch("app.workers.tasks.agent_worklist_email.send_agent_worklist_email.delay") as mock_delay:
            result = agent_worklist_email_all_tenants.run("morning")

        assert result["agents_queued"] == 2  # owner excluded
        assert mock_delay.call_count == 2

    def test_skips_loudly_with_no_email_key(self, db, monkeypatch):
        monkeypatch.setattr("app.workers.tasks.agent_worklist_email.settings.RESEND_API_KEY", "")
        with patch("app.workers.tasks.agent_worklist_email.SessionLocal", return_value=db):
            result = agent_worklist_email_all_tenants.run("morning")
        assert result["agents_queued"] == 0
