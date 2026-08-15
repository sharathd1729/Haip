"""Tests for the role-aware Analytics Dashboard rebuild
(claude-fable-5-lovely-biscuit.md): GET /dashboard/overview.

Transitively calls message_metrics.chat_response_avg_seconds/
chat_response_by_agent (LATERAL join + percentile_cont) -- same
Postgres-only pattern as test_message_metrics_by_agent.py, skip under local
SQLite, CI's Postgres testcontainer runs these for real.
"""
import os
import uuid

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.module import Module, WorkspaceModule
from app.models.capability import Capability, RoleCapability
from app.core.security import create_access_token, get_password_hash

pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (LATERAL join, percentile_cont)",
)


def _make_tenant_and_user(db, role=UserRole.OWNER):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(tenant)
    db.flush()
    user = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": tenant.id, "role": user.role.value})
    return tenant, user, token


def _grant_module(db, tenant_id, code="analytics"):
    module = db.query(Module).filter_by(code=code).first()
    if not module:
        module = Module(id=str(uuid.uuid4()), code=code, name=code.title())
        db.add(module)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=module.id, enabled=True))
    db.commit()


def _grant_capability(db, tenant_id, role, key="analytics.read"):
    cap = db.query(Capability).filter_by(key=key).first()
    if not cap:
        cap = Capability(key=key, label=key, category="analytics", is_write=False, risk="low")
        db.add(cap)
        db.flush()
    db.add(RoleCapability(id=str(uuid.uuid4()), tenant_id=tenant_id, role=role, capability_key=key, allowed=True))
    db.commit()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_owner_sees_tenant_wide_data_and_agents_table(client, db):
    tenant, user, token = _make_tenant_and_user(db, role=UserRole.OWNER)
    _grant_module(db, tenant.id)
    _grant_capability(db, tenant.id, "owner")

    resp = client.get("/api/v1/dashboard/overview", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_scope"] == "owner"
    assert "agents" in body
    assert any(a["agent_id"] == user.id for a in body["agents"])


def test_agent_role_sees_no_agents_table(client, db):
    tenant, user, token = _make_tenant_and_user(db, role=UserRole.CONCIERGE)
    _grant_module(db, tenant.id)
    _grant_capability(db, tenant.id, "concierge")

    resp = client.get("/api/v1/dashboard/overview", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_scope"] == "agent"
    assert "agents" not in body


def test_403_when_analytics_module_off(client, db):
    tenant, user, token = _make_tenant_and_user(db, role=UserRole.OWNER)
    _grant_capability(db, tenant.id, "owner")
    # Deliberately no _grant_module -- module gate should fire before the
    # capability check ever matters.

    resp = client.get("/api/v1/dashboard/overview", headers=_auth(token))
    assert resp.status_code == 403


def test_403_when_role_lacks_analytics_read_capability(client, db):
    tenant, user, token = _make_tenant_and_user(db, role=UserRole.COMPLIANCE)
    _grant_module(db, tenant.id)
    # Deliberately no _grant_capability -- compliance has no analytics.read
    # grant in authz_service._DEFAULT_GRANTS either.

    resp = client.get("/api/v1/dashboard/overview", headers=_auth(token))
    assert resp.status_code == 403


def test_tenant_isolation_agents_table(client, db):
    tenant_a, user_a, token_a = _make_tenant_and_user(db, role=UserRole.OWNER)
    _grant_module(db, tenant_a.id)
    _grant_capability(db, tenant_a.id, "owner")

    tenant_b, user_b, _ = _make_tenant_and_user(db, role=UserRole.OWNER)
    _grant_module(db, tenant_b.id)
    _grant_capability(db, tenant_b.id, "owner")

    resp = client.get("/api/v1/dashboard/overview", headers=_auth(token_a))
    assert resp.status_code == 200
    agent_ids = [a["agent_id"] for a in resp.json()["agents"]]
    assert user_b.id not in agent_ids
    assert user_a.id in agent_ids
