"""Phase 1 tests (HAIP_MCP_Connector_Plan.md, ticket 1.7) -- authz_service:
capability resolution, cross-tenant isolation, zero-row fail-closed
behavior, and cache + invalidation.
"""
import uuid

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.capability import Capability, RoleCapability
from app.core.security import get_password_hash
from app.services import authz_service

# Small catalogue subset -- enough to exercise the default-grants matrix
# without needing all 19 keys from the plan's real catalogue.
_TEST_CAPS = [
    ("leads.read", "Leads read", "leads", False, "low"),
    ("leads.write", "Leads write", "leads", True, "medium"),
    ("revenue.read", "Revenue read", "revenue", False, "medium"),
    ("users.manage", "Manage users", "admin", True, "high"),
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


def _seed_catalogue(db):
    if db.query(Capability.key).first() is not None:
        return
    for key, label, category, is_write, risk in _TEST_CAPS:
        db.add(Capability(key=key, label=label, category=category, is_write=is_write, risk=risk))
    db.commit()


class _FakeRedis:
    """In-memory stand-in for the real Redis client -- lets the cache +
    invalidation path actually run in tests instead of silently no-op'ing
    (core/cache.py's _client() fails closed to None when Redis is
    unreachable, which it always is in this test environment)."""
    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def scan_iter(self, pattern, count=100):
        import fnmatch
        return [k for k in list(self.store.keys()) if fnmatch.fnmatch(k, pattern)]

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.cache._client", lambda: fake)
    monkeypatch.setattr("app.core.cache._redis_client", None)
    return fake


class TestGetCapabilitiesHappyPath:
    def test_owner_gets_default_grants(self, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        granted = authz_service.get_capabilities(db, owner)
        assert granted == {"leads.read", "leads.write", "revenue.read", "users.manage"}

    def test_concierge_gets_narrower_grants(self, db):
        tenant = _make_tenant(db)
        concierge = _make_user(db, tenant.id, role=UserRole.CONCIERGE)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        granted = authz_service.get_capabilities(db, concierge)
        assert granted == {"leads.read", "leads.write"}
        assert "revenue.read" not in granted
        assert "users.manage" not in granted

    def test_has_capability(self, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        assert authz_service.has_capability(db, owner, "leads.read") is True
        assert authz_service.has_capability(db, owner, "nonexistent.key") is False


class TestZeroRowTenantFailsClosed:
    def test_unprovisioned_tenant_returns_empty_set(self, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        # Deliberately skip seed_default_capabilities -- simulates a tenant
        # that slipped through provisioning.

        granted = authz_service.get_capabilities(db, owner)
        assert granted == set()


class TestCrossTenantIsolation:
    def test_tenant_a_grants_do_not_leak_to_tenant_b(self, db):
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        owner_a = _make_user(db, tenant_a.id, role=UserRole.OWNER)
        owner_b = _make_user(db, tenant_b.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant_a.id)
        authz_service.seed_default_capabilities(db, tenant_b.id)

        # Narrow tenant B's owner grants directly (simulating a matrix edit).
        row = db.query(RoleCapability).filter_by(
            tenant_id=tenant_b.id, role="owner", capability_key="revenue.read",
        ).first()
        row.allowed = False
        db.commit()

        granted_a = authz_service.get_capabilities(db, owner_a)
        granted_b = authz_service.get_capabilities(db, owner_b)
        assert "revenue.read" in granted_a
        assert "revenue.read" not in granted_b


class TestCacheInvalidation:
    def test_edit_is_not_visible_until_cache_invalidated_then_is(self, db, fake_redis):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_catalogue(db)
        authz_service.seed_default_capabilities(db, tenant.id)

        granted = authz_service.get_capabilities(db, owner)
        assert "revenue.read" in granted
        assert fake_redis.store  # cache was populated

        # Mutate directly in DB, bypassing the cache -- simulates a matrix edit.
        row = db.query(RoleCapability).filter_by(
            tenant_id=tenant.id, role="owner", capability_key="revenue.read",
        ).first()
        row.allowed = False
        db.commit()

        # Stale cache still shows the old grant.
        stale = authz_service.get_capabilities(db, owner)
        assert "revenue.read" in stale

        from app.core.cache import invalidate_tenant
        invalidate_tenant(tenant.id)

        fresh = authz_service.get_capabilities(db, owner)
        assert "revenue.read" not in fresh
