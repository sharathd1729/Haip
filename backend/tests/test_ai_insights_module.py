"""AI Insights feed reactivation (2026-08-15, migration 075) -- confirms
the new require_module("ai_insights") gate on GET /analytics/insights and
POST /analytics/insights/{id}/dismiss actually 403s when the module isn't
active for a tenant, and does NOT 403 (on module grounds) when it is.
Mirrors test_analytics_module_deactivated.py's pattern -- same
"tenant_and_user's bare fixture provisions zero workspace_modules rows"
blind spot applies here, so these tests explicitly provision modules too.

dismiss_insight previously had no module gate at all (a real gap, closed
alongside this reactivation) -- covered here too.
"""
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


def test_list_insights_403_when_module_inactive(client, db):
    tenant, user, token = _make_tenant_and_user(db)
    _grant_module(db, tenant.id, "calls")  # a different module, proves this isn't zero-rows fail-closed

    resp = client.get("/api/v1/analytics/insights", headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "module_not_enabled"
    assert "ai_insights" in resp.json()["detail"]["missing_modules"]


def test_dismiss_insight_403_when_module_inactive(client, db):
    """Previously had NO gate at all -- a stale insight ID could be
    dismissed regardless of module state."""
    tenant, user, token = _make_tenant_and_user(db)
    _grant_module(db, tenant.id, "calls")

    resp = client.post("/api/v1/analytics/insights/fake-id/dismiss", headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "module_not_enabled"


def test_list_insights_not_module_gated_when_active(client, db):
    tenant, user, token = _make_tenant_and_user(db)
    _grant_module(db, tenant.id, "ai_insights")

    resp = client.get("/api/v1/analytics/insights", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_dismiss_insight_not_module_gated_when_active(client, db):
    tenant, user, token = _make_tenant_and_user(db)
    _grant_module(db, tenant.id, "ai_insights")

    resp = client.post("/api/v1/analytics/insights/fake-id/dismiss", headers=_auth(token))
    # Module gate passes; 404 because the insight doesn't exist -- not a
    # module-gate rejection.
    assert resp.status_code == 404
