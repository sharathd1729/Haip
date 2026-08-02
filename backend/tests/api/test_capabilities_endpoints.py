"""Phase 1 tests (HAIP_MCP_Connector_Plan.md, ticket 1.7) -- the
GET/PUT /api/v1/capabilities* endpoints: owner-only matrix access,
audit trail on edit, cross-tenant isolation, zero-row 409.
"""
import uuid

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.capability import Capability
from app.models.audit_event import AuditEvent
from app.core.security import create_access_token, get_password_hash
from app.services import authz_service

_TEST_CAPS = [
    ("leads.read", "Leads read", "leads", False, "low"),
    ("leads.write", "Leads write", "leads", True, "medium"),
    ("revenue.read", "Revenue read", "revenue", False, "medium"),
]


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name="Test User", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _jwt(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _seed_catalogue(db):
    if db.query(Capability.key).first() is not None:
        return
    for key, label, category, is_write, risk in _TEST_CAPS:
        db.add(Capability(key=key, label=label, category=category, is_write=is_write, risk=risk))
    db.commit()


class TestListCatalogue:
    def test_any_authed_role_can_list(self, client, db):
        tenant = _make_tenant(db)
        concierge = _make_user(db, tenant.id, role=UserRole.CONCIERGE)
        db.commit()
        _seed_catalogue(db)

        resp = client.get("/api/v1/capabilities", headers={"Authorization": f"Bearer {_jwt(concierge)}"})
        assert resp.status_code == 200
        keys = {c["key"] for c in resp.json()}
        assert "leads.read" in keys


class TestMyCapabilities:
    def test_manager_sees_only_own_role_grants(self, client, db):
        """4.2: /matrix is owner-only, but a manager can also mint an MCP
        token (0.6) and needs to answer 'what can this token do' without
        needing owner access to the full matrix."""
        tenant = _make_tenant(db)
        manager = _make_user(db, tenant.id, role=UserRole.MANAGER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        resp = client.get("/api/v1/capabilities/mine", headers={"Authorization": f"Bearer {_jwt(manager)}"})
        assert resp.status_code == 200
        keys = {c["key"] for c in resp.json()}
        assert keys == {"leads.read", "leads.write", "revenue.read"}  # manager has all 3 by default

    def test_zero_row_tenant_returns_empty_not_error(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        # Deliberately not seeded.

        resp = client.get("/api/v1/capabilities/mine", headers={"Authorization": f"Bearer {_jwt(owner)}"})
        assert resp.status_code == 200
        assert resp.json() == []


class TestMatrixOwnerOnly:
    def test_owner_can_get_matrix(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        resp = client.get("/api/v1/capabilities/matrix", headers={"Authorization": f"Bearer {_jwt(owner)}"})
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == len(_TEST_CAPS) * 8  # 8 roles

    def test_manager_cannot_get_matrix(self, client, db):
        tenant = _make_tenant(db)
        manager = _make_user(db, tenant.id, role=UserRole.MANAGER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        resp = client.get("/api/v1/capabilities/matrix", headers={"Authorization": f"Bearer {_jwt(manager)}"})
        assert resp.status_code == 403

    def test_manager_cannot_put_matrix(self, client, db):
        tenant = _make_tenant(db)
        manager = _make_user(db, tenant.id, role=UserRole.MANAGER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        resp = client.put(
            "/api/v1/capabilities/matrix",
            json={"edits": [{"role": "manager", "capability_key": "revenue.read", "allowed": True}]},
            headers={"Authorization": f"Bearer {_jwt(manager)}"},
        )
        assert resp.status_code == 403

    def test_zero_row_tenant_matrix_409(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        # Deliberately not seeded.

        resp = client.get("/api/v1/capabilities/matrix", headers={"Authorization": f"Bearer {_jwt(owner)}"})
        assert resp.status_code == 409


class TestMatrixEditAudited:
    def test_owner_edit_persists_and_writes_audit_event(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        resp = client.put(
            "/api/v1/capabilities/matrix",
            json={"edits": [{"role": "concierge", "capability_key": "revenue.read", "allowed": True}]},
            headers={"Authorization": f"Bearer {_jwt(owner)}"},
        )
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        edited = [e for e in entries if e["role"] == "concierge" and e["capability_key"] == "revenue.read"]
        assert edited[0]["allowed"] is True

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="role_capabilities.change").all()
        assert len(events) == 1
        assert events[0].actor_user_id == owner.id
        assert events[0].payload["edits"] == [{"role": "concierge", "capability_key": "revenue.read", "allowed": True}]

    def test_unknown_capability_key_rejected(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        resp = client.put(
            "/api/v1/capabilities/matrix",
            json={"edits": [{"role": "owner", "capability_key": "does.not.exist", "allowed": True}]},
            headers={"Authorization": f"Bearer {_jwt(owner)}"},
        )
        assert resp.status_code == 400


class TestCrossTenantIsolation:
    def test_owner_edit_does_not_touch_other_tenants_matrix(self, client, db):
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        owner_a = _make_user(db, tenant_a.id, role=UserRole.OWNER)
        concierge_b = _make_user(db, tenant_b.id, role=UserRole.CONCIERGE)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant_a.id)
        authz_service.seed_default_capabilities(db, tenant_b.id)

        # Grant tenant A's concierge role revenue.read (normally denied by default).
        client.put(
            "/api/v1/capabilities/matrix",
            json={"edits": [{"role": "concierge", "capability_key": "revenue.read", "allowed": True}]},
            headers={"Authorization": f"Bearer {_jwt(owner_a)}"},
        )

        # Tenant B's concierge (same role, different tenant) must still be denied.
        granted_b = authz_service.get_capabilities(db, concierge_b)
        assert "revenue.read" not in granted_b
