"""Phase 2 tests (HAIP_MCP_Connector_Plan.md, ticket 2.6) -- wiring MCP to
the capability registry: tools/list filtering, tools/call re-check, token
scope narrowing (D2), and one-audit-row-per-call (D4).

Note: MCP access itself is still locked to owner/manager roles only
(Phase 0 ticket 0.7, `_MCP_ALLOWED_ROLES` in app/mcp/server.py) -- per the
plan's own §6 sequencing note, that restriction stays until Phase 1's
registry has landed, which it now has. A concierge/marketing PAT can't
reach the capability gate at all yet in production; these tests
monkeypatch `_MCP_ALLOWED_ROLES` to prove the capability layer itself is
correct *now*, so it's ready the moment that restriction is lifted --
exactly the scenario Phase 1+2 exist to prepare for.
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.audit_event import AuditEvent
from app.models.capability import Capability
from app.core.security import get_password_hash
from app.services import authz_service, token_service

# The 5 real capability keys the current 9-tool set actually uses.
_TOOL_CAPS = [
    ("leads.read", "Leads read", "leads", False, "low"),
    ("leads.write", "Leads write", "leads", True, "medium"),
    ("conversations.read", "Conversations read", "conversations", False, "low"),
    ("conversations.send", "Conversations send", "conversations", True, "medium"),
    ("guests.read", "Guests read", "guests", False, "low"),
]


def _seed_capabilities(db, *tenant_ids):
    if db.query(Capability.key).first() is None:
        for key, label, category, is_write, risk in _TOOL_CAPS:
            db.add(Capability(key=key, label=label, category=category, is_write=is_write, risk=risk))
        db.commit()
    for tenant_id in tenant_ids:
        authz_service.seed_default_capabilities(db, tenant_id)


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


class _NoCloseSession:
    """See test_mcp_phase0.py -- mcp_endpoint opens its own SessionLocal(),
    a separate connection from the test's transactional `db` fixture.
    Patch it to reuse the test session so writes are visible, with close()
    stubbed so mcp_endpoint's own `finally: db.close()` doesn't tear the
    fixture down mid-test."""
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


def _admit_role(role: UserRole):
    """Context manager-style helper: temporarily widen _MCP_ALLOWED_ROLES
    to admit a role beyond owner/manager, for testing the capability layer
    in isolation from the still-active Phase 0 restriction."""
    return patch("app.mcp.server._MCP_ALLOWED_ROLES", {UserRole.OWNER, UserRole.MANAGER, role})


class TestToolsListFiltersByCapability:
    def test_marketing_role_sees_only_its_granted_tools(self, client, db):
        """marketing has leads.read + guests.read but not conversations.read,
        conversations.send, or leads.write -- should see exactly 3 of 9 tools."""
        tenant = _make_tenant(db)
        marketing = _make_user(db, tenant.id, role=UserRole.MARKETING)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, marketing.id, "Claude")
        db.commit()

        with _admit_role(UserRole.MARKETING):
            resp = _jsonrpc(client, db, raw_pat, "tools/list")

        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert names == {"list_leads", "get_lead_detail", "search_guests"}


class TestToolsCallReChecksCapability:
    def test_marketing_cannot_call_hidden_tool_by_name(self, client, db):
        """tools/list filtering is UX only -- calling a tool never shown to
        this role must still be denied server-side (plan invariant #1)."""
        tenant = _make_tenant(db)
        marketing = _make_user(db, tenant.id, role=UserRole.MARKETING)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, marketing.id, "Claude")
        db.commit()

        with _admit_role(UserRole.MARKETING):
            resp = _jsonrpc(client, db, raw_pat, "tools/call", {
                "name": "move_lead_stage", "arguments": {"inquiry_id": "x", "new_stage_id": "y"},
            })

        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32001


class TestTokenScopeNarrowsRole:
    def test_read_scoped_token_cannot_exceed_role_into_writes(self, client, db):
        """D2: an owner has leads.write via role, but a token minted with
        scopes=["read"] must not be able to use it -- token narrows, role
        alone is not enough."""
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Read-only Claude", scopes=["read"])
        db.commit()

        list_resp = _jsonrpc(client, db, raw_pat, "tools/list")
        names = {t["name"] for t in list_resp.json()["result"]["tools"]}
        assert "move_lead_stage" not in names
        assert "add_note" not in names
        assert "approve_and_send_draft" not in names
        assert "list_leads" in names  # read capability still present

        call_resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "move_lead_stage", "arguments": {"inquiry_id": "x", "new_stage_id": "y"},
        })
        assert call_resp.json()["error"]["code"] == -32001

    def test_full_scope_token_gets_everything_role_grants(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Full Claude")  # default scopes
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        # Phase 3 added assign_lead/update_lead_fields/add_guest_signal,
        # all leads.write -- this test's seeded catalogue only covers the 5
        # capability keys the original 9 tools use, so only those plus the
        # 3 new leads.write tools are visible (the Phase 3 tools gated on
        # calls.read/bookings.read/revenue.read/etc. aren't in this test's
        # catalogue at all, so they can't appear regardless of role).
        assert names == {
            "list_recent_conversations", "get_conversation_thread", "search_conversations",
            "list_leads", "get_lead_detail", "search_guests",
            "approve_and_send_draft", "move_lead_stage", "add_note",
            "assign_lead", "update_lead_fields", "add_guest_signal",
        }


class TestOneAuditRowPerCall:
    def test_successful_call_writes_exactly_one_audit_row(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {"name": "list_leads", "arguments": {}})
        assert resp.status_code == 200

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.tool.list_leads").all()
        assert len(events) == 1
        assert events[0].payload["is_error"] is False
        assert events[0].payload["token_id"]
        assert events[0].payload["capability"] == "leads.read"
        assert events[0].actor_user_id == owner.id

    def test_errored_call_still_writes_exactly_one_audit_row(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_lead_detail", "arguments": {"inquiry_id": "does-not-exist"},
        })
        assert resp.status_code == 200
        assert resp.json()["result"]["isError"] is True

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.tool.get_lead_detail").all()
        assert len(events) == 1
        assert events[0].payload["is_error"] is True

    def test_audit_payload_redacts_free_text_args(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "search_guests", "arguments": {"query": "+919876543210"},
        })
        assert resp.status_code == 200

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.tool.search_guests").all()
        assert len(events) == 1
        assert events[0].payload["args"]["query"] != "+919876543210"
        assert len(events[0].payload["args"]["query"]) == 12  # sha256[:12]

    def test_audit_target_inferred_from_inquiry_id(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)

        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Guest", phone="+910000000009")
        db.add(guest); db.flush()
        inquiry = Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
            stage=InquiryStage.NEW, source=InquirySource.META_IG,
        )
        db.add(inquiry); db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_lead_detail", "arguments": {"inquiry_id": inquiry.id},
        })
        assert resp.status_code == 200

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.tool.get_lead_detail").all()
        assert len(events) == 1
        assert events[0].target_type == "inquiry"
        assert events[0].target_id == inquiry.id


class TestZeroRowTenantFailsClosedAtMcp:
    def test_unprovisioned_tenant_sees_no_tools(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        # Deliberately not seeded -- unprovisioned tenant.
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/list")
        assert resp.status_code == 200
        assert resp.json()["result"]["tools"] == []
