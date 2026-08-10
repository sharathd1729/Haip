"""Dashboards/analytics/insights deactivation (2026-08-08) -- confirm the
router-level require_module("analytics") dependency added to dashboard.py,
dashboards.py, analytics_sections.py, and analytics_intelligence.py
actually 403s when the 'analytics' module isn't active for a tenant, and
does NOT 403 (on module grounds) when it is.

tenant_and_user's bare fixture provisions zero workspace_modules rows at
all, which already 403s via the pre-existing "workspace_unprovisioned"
fail-closed path (app/api/v1/deps.py) for an unrelated reason -- these
tests provision modules explicitly so the specific "analytics module is
off" 403 is what's actually being exercised, not that fail-closed path.
"""
import os
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.module import Module, WorkspaceModule
from app.core.security import create_access_token, get_password_hash


def _make_tenant_and_user(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(tenant)
    db.flush()
    user = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="Owner",
        email=f"o-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": tenant.id, "role": user.role.value})
    return tenant, user, token


def _grant_module(db, tenant_id, code, enabled=True):
    module = db.query(Module).filter_by(code=code).first()
    if not module:
        module = Module(id=str(uuid.uuid4()), code=code, name=code.title())
        db.add(module)
        db.flush()
    db.add(WorkspaceModule(
        id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=module.id, enabled=enabled,
    ))
    db.commit()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


_GATED_ENDPOINTS = [
    "/api/v1/dashboard",
    "/api/v1/dashboards",
    "/api/v1/analytics/guests",
    "/api/v1/analytics/intent",
]


@pytest.mark.parametrize("path", _GATED_ENDPOINTS)
def test_analytics_endpoints_403_when_module_inactive(client, db, path):
    tenant, user, token = _make_tenant_and_user(db)
    # Provisioned with a DIFFERENT module (proves this isn't just the
    # zero-rows "workspace_unprovisioned" fail-closed path) but explicitly
    # NOT 'analytics'.
    _grant_module(db, tenant.id, "calls")

    resp = client.get(path, headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "module_not_enabled"
    assert "analytics" in resp.json()["detail"]["missing_modules"]


@pytest.mark.parametrize("path", [
    p for p in _GATED_ENDPOINTS
    # get_dashboard() always runs a Postgres-only window-function query
    # (unrelated to this module-gate change -- same class of pre-existing
    # SQLite incompatibility as test_dashboard_stage_fix.py); skip it here
    # under local SQLite so this file only exercises the module gate.
    if not (p == "/api/v1/dashboard" and "sqlite" in os.environ.get("DATABASE_URL", "sqlite"))
])
def test_analytics_endpoints_not_module_gated_when_active(client, db, path):
    tenant, user, token = _make_tenant_and_user(db)
    _grant_module(db, tenant.id, "analytics")

    resp = client.get(path, headers=_auth(token))
    # Downstream business logic may still fail for unrelated reasons -- the
    # only thing under test here is that it's not the module gate itself.
    if resp.status_code == 403:
        assert resp.json().get("detail", {}).get("error") != "module_not_enabled"
