"""
Phase 0 tests (HAIP_MCP_Connector_Plan.md, ticket 0.9) -- the auth-gating
hardening pass for the MCP server: D1 (deactivated user), D5 (rate limit,
covered separately since it needs Redis), the owner/manager-only access
restriction (issuance gate + runtime gate), and cross-tenant isolation.

Note on status codes: /mcp is JSON-RPC over HTTP, not REST -- every response
(including auth failures) is HTTP 200 with a JSON-RPC `error` object in the
body (`error.code == -32001` for auth failures), not an HTTP 401. That's the
existing protocol design in app/mcp/server.py, not something this phase
changes.
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.core.security import create_access_token, get_password_hash
from app.models.capability import Capability
from app.services import authz_service, token_service


def _seed_capabilities(db, *tenant_ids):
    """Phase 2 landed the capability gate on every tools/call -- tests that
    exercise an actual tool response (not just an auth-layer denial) need a
    provisioned capability matrix or every call 403s before reaching the
    behavior under test. `leads.read` is the only key these particular
    tests' tools (`list_leads`/`get_lead_detail`) need."""
    if db.query(Capability.key).first() is None:
        db.add(Capability(key="leads.read", label="Leads read", category="leads", is_write=False, risk="low"))
        db.commit()
    for tenant_id in tenant_ids:
        authz_service.seed_default_capabilities(db, tenant_id)


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER, is_active=True):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name="Test User", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=is_active,
    )
    db.add(u); db.flush(); return u


def _jwt(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


class _NoCloseSession:
    """mcp_endpoint always calls SessionLocal() itself (it runs outside
    FastAPI's per-request DI cycle, same as a Celery task -- see
    app/mcp/server.py's own docstring), so overriding get_db in the client
    fixture doesn't reach it: it opens a genuinely separate DB connection.
    On file-backed SQLite that connection can't see the test `db` fixture's
    writes, since those live inside an outer transaction
    (conftest.py's `db` fixture) that's rolled back at teardown and never
    truly committed to disk.

    Wrap the test's own session so `SessionLocal()` returns it instead --
    same connection, so every write is visible -- but no-op close() so
    mcp_endpoint's `finally: db.close()` doesn't tear down the fixture's
    session out from under the rest of the test.
    """
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


def _jsonrpc(client, db, raw_pat, method, params=None):
    with patch("app.mcp.server.SessionLocal", lambda: _NoCloseSession(db)):
        return client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers={"Authorization": f"Bearer {raw_pat}"},
        )


# ── D1: deactivated/soft-deleted user ──────────────────────────────────────────

class TestDeactivatedUserDenied:
    def test_valid_pat_but_deactivated_user_denied(self, client, db):
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        raw_pat, _ = token_service.generate_token(db, tenant.id, user.id, "Claude")
        db.commit()

        # Offboard the user -- their PAT is still cryptographically valid.
        user.is_active = False
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32001

    def test_valid_pat_but_soft_deleted_user_denied(self, client, db):
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        raw_pat, _ = token_service.generate_token(db, tenant.id, user.id, "Claude")
        db.commit()

        user.is_deleted = True
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.json()["error"]["code"] == -32001


# ── Expired / revoked tokens ─────────────────────────────────────────────────

class TestTokenLifecycleDenied:
    def test_expired_pat_denied(self, client, db):
        from datetime import datetime, timedelta, timezone
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        raw_pat, record = token_service.generate_token(db, tenant.id, user.id, "Claude")
        record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.json()["error"]["code"] == -32001

    def test_revoked_pat_denied(self, client, db):
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        raw_pat, record = token_service.generate_token(db, tenant.id, user.id, "Claude")
        db.commit()
        token_service.revoke_token(db, tenant_id=tenant.id, user_id=user.id, token_id=record.id)

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.json()["error"]["code"] == -32001

    def test_new_pat_has_a_default_expiry(self, db):
        """0.5: generate_token used to never set expires_at -- tokens were immortal."""
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _, record = token_service.generate_token(db, tenant.id, user.id, "Claude")
        assert record.expires_at is not None


# ── Owner/manager-only access (issuance gate + runtime gate) ───────────────────

class TestOwnerManagerOnlyAccess:
    def test_concierge_cannot_create_pat(self, client, db):
        """0.6: issuance gate."""
        tenant = _make_tenant(db)
        concierge = _make_user(db, tenant.id, role=UserRole.CONCIERGE)
        db.commit()

        resp = client.post(
            "/api/v1/mcp-tokens", json={"name": "Claude"},
            headers={"Authorization": f"Bearer {_jwt(concierge)}"},
        )
        assert resp.status_code == 403

    def test_owner_can_create_pat(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()

        resp = client.post(
            "/api/v1/mcp-tokens", json={"name": "Claude"},
            headers={"Authorization": f"Bearer {_jwt(owner)}"},
        )
        assert resp.status_code == 200

    def test_manager_can_create_pat(self, client, db):
        tenant = _make_tenant(db)
        manager = _make_user(db, tenant.id, role=UserRole.MANAGER)
        db.commit()

        resp = client.post(
            "/api/v1/mcp-tokens", json={"name": "Claude"},
            headers={"Authorization": f"Bearer {_jwt(manager)}"},
        )
        assert resp.status_code == 200

    def test_pat_held_by_user_demoted_to_concierge_denied_at_mcp(self, client, db):
        """0.7: the runtime gate -- the one ticket 0.9 calls out as 'the one
        that gets forgotten'. Issuance-time gating alone isn't enough."""
        tenant = _make_tenant(db)
        manager = _make_user(db, tenant.id, role=UserRole.MANAGER)
        db.commit()
        raw_pat, _ = token_service.generate_token(db, tenant.id, manager.id, "Claude")
        db.commit()

        # Demoted after the token was already issued while still a manager.
        manager.role = UserRole.CONCIERGE
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.json()["error"]["code"] == -32001

    def test_reservations_role_pat_denied_at_mcp(self, client, db):
        """A PAT that predates the owner/manager-only restriction (or one
        issued before 0.6 shipped) must still be denied at runtime by 0.7,
        independent of when/how it was created."""
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, role=UserRole.RESERVATIONS)
        db.commit()
        # Bypass the issuance gate entirely (simulates a pre-existing token)
        raw_pat, _ = token_service.generate_token(db, tenant.id, agent.id, "Legacy token")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.json()["error"]["code"] == -32001


# ── Cross-tenant isolation ──────────────────────────────────────────────────

class TestCrossTenantIsolation:
    def test_pat_cannot_read_another_tenants_lead(self, client, db):
        tenant_a = _make_tenant(db, "Tenant A")
        tenant_b = _make_tenant(db, "Tenant B")
        owner_a = _make_user(db, tenant_a.id, role=UserRole.OWNER)
        owner_b = _make_user(db, tenant_b.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant_a.id, tenant_b.id)

        guest_a = Guest(id=str(uuid.uuid4()), tenant_id=tenant_a.id, name="Guest A", phone="+910000000001")
        db.add(guest_a); db.flush()
        inquiry_a = Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant_a.id, guest_id=guest_a.id,
            stage=InquiryStage.NEW, source=InquirySource.META_IG,
        )
        db.add(inquiry_a); db.commit()

        raw_pat_b, _ = token_service.generate_token(db, tenant_b.id, owner_b.id, "Claude")
        db.commit()

        # Tenant B's token asking for tenant A's inquiry by ID must not see it.
        resp = _jsonrpc(client, db, raw_pat_b, "tools/call", {
            "name": "get_lead_detail", "arguments": {"inquiry_id": inquiry_a.id},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["isError"] is True
        assert inquiry_a.id not in data["result"]["content"][0]["text"] or "not found" in data["result"]["content"][0]["text"].lower()

    def test_pat_lists_only_own_tenants_leads(self, client, db):
        tenant_a = _make_tenant(db, "Tenant A")
        tenant_b = _make_tenant(db, "Tenant B")
        owner_a = _make_user(db, tenant_a.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant_a.id, tenant_b.id)

        guest_a = Guest(id=str(uuid.uuid4()), tenant_id=tenant_a.id, name="Guest A", phone="+910000000002")
        db.add(guest_a); db.flush()
        db.add(Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant_a.id, guest_id=guest_a.id,
            stage=InquiryStage.NEW, source=InquirySource.META_IG,
        ))
        db.commit()

        raw_pat_a, _ = token_service.generate_token(db, tenant_a.id, owner_a.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat_a, "tools/call", {"name": "list_leads", "arguments": {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["isError"] is False
        assert "Guest A" in data["result"]["content"][0]["text"] or guest_a.id in data["result"]["content"][0]["text"]


# ── 0.3: result-size cap ─────────────────────────────────────────────────────

def test_to_text_truncates_oversized_results():
    from app.mcp.server import _to_text, _MAX_RESULT_CHARS
    huge = {"data": "x" * (_MAX_RESULT_CHARS + 5000)}
    text = _to_text(huge)
    assert len(text) < len(huge["data"]) + 5000  # actually shorter than the untruncated dump
    assert '"truncated": true' in text


def test_to_text_leaves_small_results_untouched():
    from app.mcp.server import _to_text
    small = {"hello": "world"}
    assert _to_text(small) == '{"hello": "world"}'
