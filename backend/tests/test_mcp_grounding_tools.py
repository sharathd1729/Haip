"""Tests for HAIP_AI_Autonomy_Plan.md Phase 1, ticket 3: check_availability
and get_quote MCP tools.
"""
import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.property import Property, RatePlan, Stay, BlockedDate, PropertyAddOn
from app.models.capability import Capability
from app.core.security import get_password_hash
from app.services import authz_service, token_service

_TOOL_CAPS = [
    ("bookings.read", "Bookings read", "bookings", False, "low"),
    ("revenue.read", "Revenue read", "revenue", False, "medium"),
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


def _make_property(db, tenant_id, name="Villa Test", max_adults=6):
    prop = Property(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        slug=f"villa-{uuid.uuid4().hex[:6]}", type="villa", is_active=True,
        max_adults=max_adults, city="Goa",
    )
    db.add(prop); db.flush()
    db.add(RatePlan(
        id=str(uuid.uuid4()), tenant_id=tenant_id, property_id=prop.id,
        name="Base Rate", base_price_per_night=10000, is_active=True,
    ))
    db.commit()
    return prop


class _NoCloseSession:
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


class TestCheckAvailability:
    def test_finds_available_property(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        prop = _make_property(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "check_availability",
            "arguments": {"from_date": "2026-12-10", "to_date": "2026-12-12", "adults": 4},
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        assert prop.id in result["content"][0]["text"]
        assert "Villa Test" in result["content"][0]["text"]

    def test_excludes_property_with_conflicting_stay(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        prop = _make_property(db, tenant.id)

        from app.models.guest import Guest
        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Existing Guest", phone="+910000000077")
        db.add(guest); db.flush()
        db.add(Stay(
            id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, property_id=prop.id,
            check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), status="confirmed",
        ))
        db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "check_availability",
            "arguments": {"from_date": "2026-12-10", "to_date": "2026-12-12", "adults": 2},
        })
        result = resp.json()["result"]
        assert prop.id not in result["content"][0]["text"]

    def test_excludes_property_over_capacity(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        prop = _make_property(db, tenant.id, max_adults=2)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "check_availability",
            "arguments": {"from_date": "2026-12-10", "to_date": "2026-12-12", "adults": 6},
        })
        result = resp.json()["result"]
        assert prop.id not in result["content"][0]["text"]

    def test_denied_without_bookings_read(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        from app.models.capability import RoleCapability
        row = db.query(RoleCapability).filter_by(tenant_id=tenant.id, role="owner", capability_key="bookings.read").first()
        row.allowed = False
        db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "check_availability", "arguments": {"from_date": "2026-12-10", "to_date": "2026-12-12"},
        })
        assert resp.json()["error"]["code"] == -32001


class TestGetQuote:
    def test_builds_quote_with_gst_and_advance(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        prop = _make_property(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_quote",
            "arguments": {"property_id": prop.id, "from_date": "2026-12-10", "to_date": "2026-12-12", "adults": 2},
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        text = result["content"][0]["text"]
        # 2 nights x 10000 = 20000 subtotal, 12% GST = 2400, total = 22400
        assert "20000" in text
        assert "2400" in text
        assert "22400" in text

    def test_includes_selected_addon(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        prop = _make_property(db, tenant.id)
        addon = PropertyAddOn(
            id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=prop.id,
            name="Candle-lit dinner", price=3000, price_type="per_stay", is_active=True,
        )
        db.add(addon); db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_quote",
            "arguments": {
                "property_id": prop.id, "from_date": "2026-12-10", "to_date": "2026-12-12",
                "adults": 2, "addon_ids": [addon.id],
            },
        })
        text = resp.json()["result"]["content"][0]["text"]
        assert "Candle-lit dinner" in text

    def test_no_rate_configured_returns_tool_error(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        # Property with no RatePlan at all.
        prop = Property(
            id=str(uuid.uuid4()), tenant_id=tenant.id, name="No Rate Villa",
            slug=f"no-rate-{uuid.uuid4().hex[:6]}", type="villa", is_active=True, max_adults=4,
        )
        db.add(prop); db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_quote",
            "arguments": {"property_id": prop.id, "from_date": "2026-12-10", "to_date": "2026-12-12"},
        })
        result = resp.json()["result"]
        assert result["isError"] is True
        assert "check_availability" in result["content"][0]["text"]


class TestTenantIsolation:
    def test_cannot_get_quote_for_another_tenants_property(self, client, db):
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        owner_b = _make_user(db, tenant_b.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant_a.id, tenant_b.id)
        prop_a = _make_property(db, tenant_a.id, name="Tenant A's Villa")

        raw_pat_b, _ = token_service.generate_token(db, tenant_b.id, owner_b.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat_b, "tools/call", {
            "name": "get_quote",
            "arguments": {"property_id": prop_a.id, "from_date": "2026-12-10", "to_date": "2026-12-12"},
        })
        result = resp.json()["result"]
        assert result["isError"] is True  # not found under tenant B's scope

    def test_check_availability_never_shows_another_tenants_property(self, client, db):
        tenant_a = _make_tenant(db, "A")
        tenant_b = _make_tenant(db, "B")
        owner_b = _make_user(db, tenant_b.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant_a.id, tenant_b.id)
        prop_a = _make_property(db, tenant_a.id, name="Tenant A's Secret Villa")

        raw_pat_b, _ = token_service.generate_token(db, tenant_b.id, owner_b.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat_b, "tools/call", {
            "name": "check_availability",
            "arguments": {"from_date": "2026-12-10", "to_date": "2026-12-12"},
        })
        text = resp.json()["result"]["content"][0]["text"]
        assert prop_a.id not in text
        assert "Secret Villa" not in text


class TestAuditTargetsProperty:
    def test_get_quote_audit_row_targets_the_property(self, client, db):
        from app.models.audit_event import AuditEvent

        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        prop = _make_property(db, tenant.id)
        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_quote",
            "arguments": {"property_id": prop.id, "from_date": "2026-12-10", "to_date": "2026-12-12"},
        })

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.tool.get_quote").all()
        assert len(events) == 1
        assert events[0].target_type == "property"
        assert events[0].target_id == prop.id
