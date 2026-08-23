"""Tests for GET /users/{user_id}/scorecard and GET /users/{user_id}/messages
-- the Agent Profile page's data sources (agent-attribution dashboard plan)."""
import uuid
from unittest.mock import patch

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType
from app.core.security import create_access_token, get_password_hash


@pytest.fixture(autouse=True)
def _no_postgres_lateral_join():
    """See test_agent_analytics_service.py -- chat_response_by_agent is
    Postgres-only raw SQL, unrunnable against the SQLite test DB."""
    with patch("app.services.message_metrics.chat_response_by_agent", return_value=[]):
        yield


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestScorecardEndpoint:
    def test_self_view_happy_path(self, client, db):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id)
        db.commit()

        resp = client.get(f"/api/v1/users/{agent.id}/scorecard", headers=_auth(_token(agent)))
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == agent.id

    def test_owner_can_view_another_agent(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent = _make_user(db, tenant.id, name="Agent")
        db.commit()

        resp = client.get(f"/api/v1/users/{agent.id}/scorecard", headers=_auth(_token(owner)))
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == agent.id

    def test_agent_cannot_view_another_agent(self, client, db):
        tenant = _make_tenant(db)
        agent1 = _make_user(db, tenant.id, name="Agent1")
        agent2 = _make_user(db, tenant.id, name="Agent2")
        db.commit()

        resp = client.get(f"/api/v1/users/{agent2.id}/scorecard", headers=_auth(_token(agent1)))
        assert resp.status_code == 403


class TestMessagesEndpoint:
    def test_returns_only_this_agents_sent_messages(self, client, db):
        tenant = _make_tenant(db)
        agent1 = _make_user(db, tenant.id, name="Agent1")
        agent2 = _make_user(db, tenant.id, name="Agent2")
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Guest", phone="+919876500001")
        db.add(guest); db.flush()
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.flush()
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
            direction="outbound", channel="whatsapp", body="Hi there",
            sender_id=agent1.id, is_ai_generated=False,
        ))
        db.add(Message(
            id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id,
            direction="outbound", channel="whatsapp", body="Hi from AI",
            is_ai_generated=True,
        ))
        db.commit()

        resp = client.get(
            f"/api/v1/users/{agent1.id}/messages?date_preset=this_month",
            headers=_auth(_token(agent1)),
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == conv.id
        assert rows[0]["guest_name"] == "Guest"
        assert rows[0]["message_count"] == 1

        resp2 = client.get(
            f"/api/v1/users/{agent2.id}/messages?date_preset=this_month",
            headers=_auth(_token(agent2)),
        )
        assert resp2.json() == []

    def test_forbidden_for_other_agent(self, client, db):
        tenant = _make_tenant(db)
        agent1 = _make_user(db, tenant.id, name="Agent1")
        agent2 = _make_user(db, tenant.id, name="Agent2")
        db.commit()

        resp = client.get(f"/api/v1/users/{agent2.id}/messages", headers=_auth(_token(agent1)))
        assert resp.status_code == 403
