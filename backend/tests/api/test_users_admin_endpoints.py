"""Tests for admin-triggered user edits: PATCH /users/{id} email updates
and POST /users/{id}/send-password-reset (Rathaa employee-email-correction
+ credential-delivery request)."""
import uuid
from unittest.mock import patch

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import create_access_token, get_password_hash


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent", email=None):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=email or f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestUpdateUserEmail:
    def test_owner_can_update_a_members_email(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent = _make_user(db, tenant.id, name="Agent", email="old@ratha.in")
        db.commit()

        resp = client.patch(
            f"/api/v1/users/{agent.id}",
            json={"email": "new@ratha.in"},
            headers=_auth(_token(owner)),
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "new@ratha.in"
        db.refresh(agent)
        assert agent.email == "new@ratha.in"

    def test_rejects_email_already_used_by_another_member_same_tenant(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent1 = _make_user(db, tenant.id, name="Agent1", email="taken@ratha.in")
        agent2 = _make_user(db, tenant.id, name="Agent2", email="agent2@ratha.in")
        db.commit()

        resp = client.patch(
            f"/api/v1/users/{agent2.id}",
            json={"email": "taken@ratha.in"},
            headers=_auth(_token(owner)),
        )
        assert resp.status_code == 400
        db.refresh(agent2)
        assert agent2.email == "agent2@ratha.in"

    def test_same_email_allowed_across_different_tenants(self, client, db):
        tenant1 = _make_tenant(db, "T1")
        tenant2 = _make_tenant(db, "T2")
        owner1 = _make_user(db, tenant1.id, role=UserRole.OWNER, name="Owner1")
        _make_user(db, tenant2.id, name="OtherTenantAgent", email="shared@example.com")
        agent = _make_user(db, tenant1.id, name="Agent", email="agent@t1.com")
        db.commit()

        resp = client.patch(
            f"/api/v1/users/{agent.id}",
            json={"email": "shared@example.com"},
            headers=_auth(_token(owner1)),
        )
        assert resp.status_code == 200

    def test_forbidden_for_non_owner_manager(self, client, db):
        tenant = _make_tenant(db)
        agent1 = _make_user(db, tenant.id, name="Agent1")
        agent2 = _make_user(db, tenant.id, name="Agent2", email="old@ratha.in")
        db.commit()

        resp = client.patch(
            f"/api/v1/users/{agent2.id}",
            json={"email": "new@ratha.in"},
            headers=_auth(_token(agent1)),
        )
        assert resp.status_code == 403


class TestSendPasswordReset:
    def test_owner_triggers_reset_email_for_a_member(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent = _make_user(db, tenant.id, name="Agent", email="agent@ratha.in")
        db.commit()

        with patch(
            "app.api.v1.endpoints.auth.issue_password_reset_email",
            return_value=True,
        ) as mock_issue:
            resp = client.post(
                f"/api/v1/users/{agent.id}/send-password-reset",
                headers=_auth(_token(owner)),
            )

        assert resp.status_code == 200
        assert "agent@ratha.in" in resp.json()["message"]
        mock_issue.assert_called_once()

    def test_returns_502_when_email_send_fails(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent = _make_user(db, tenant.id, name="Agent")
        db.commit()

        with patch("app.api.v1.endpoints.auth.issue_password_reset_email", return_value=False):
            resp = client.post(
                f"/api/v1/users/{agent.id}/send-password-reset",
                headers=_auth(_token(owner)),
            )
        assert resp.status_code == 502

    def test_404_for_nonexistent_user(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        db.commit()

        resp = client.post(
            f"/api/v1/users/{uuid.uuid4()}/send-password-reset",
            headers=_auth(_token(owner)),
        )
        assert resp.status_code == 404

    def test_forbidden_for_non_owner_manager(self, client, db):
        tenant = _make_tenant(db)
        agent1 = _make_user(db, tenant.id, name="Agent1")
        agent2 = _make_user(db, tenant.id, name="Agent2")
        db.commit()

        resp = client.post(
            f"/api/v1/users/{agent2.id}/send-password-reset",
            headers=_auth(_token(agent1)),
        )
        assert resp.status_code == 403

    def test_cannot_trigger_reset_for_another_tenants_user(self, client, db):
        tenant1 = _make_tenant(db, "T1")
        tenant2 = _make_tenant(db, "T2")
        owner1 = _make_user(db, tenant1.id, role=UserRole.OWNER, name="Owner1")
        other_tenant_agent = _make_user(db, tenant2.id, name="OtherTenantAgent")
        db.commit()

        resp = client.post(
            f"/api/v1/users/{other_tenant_agent.id}/send-password-reset",
            headers=_auth(_token(owner1)),
        )
        assert resp.status_code == 404
