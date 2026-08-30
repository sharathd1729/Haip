"""Targets API: happy path, role gate, cross-tenant isolation.

Per CLAUDE.md every new endpoint needs those three.
"""
import uuid

from tests.conftest import *  # noqa: F401,F403

from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User, UserRole


def _headers(fixture):
    return {"Authorization": f"Bearer {fixture['access_token']}"}


def _tenant_id(fixture):
    t = fixture["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_user(db, tenant_id, role):
    from app.core.security import create_access_token, get_password_hash
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value}-user",
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("testpassword123"), role=role, is_active=True,
    )
    db.add(u); db.commit()
    token = create_access_token(data={"sub": u.id, "tenant_id": tenant_id, "role": role.value})
    return u, {"Authorization": f"Bearer {token}"}


class TestSetTarget:
    def test_owner_can_set_a_tenant_target(self, client, db, tenant_and_user):
        resp = client.put("/api/v1/targets", headers=_headers(tenant_and_user), json={
            "scope_type": "tenant", "period_month": "2026-07-01", "target_amount": "6300000",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert float(body["target_amount"]) == 6300000
        # 6,300,000 / 31 days
        assert round(float(body["daily_target"]), 2) == round(6300000 / 31, 2)

    def test_setting_twice_updates_rather_than_duplicating(self, client, db, tenant_and_user):
        h = _headers(tenant_and_user)
        client.put("/api/v1/targets", headers=h, json={
            "scope_type": "tenant", "period_month": "2026-07-01", "target_amount": "100",
        })
        client.put("/api/v1/targets", headers=h, json={
            "scope_type": "tenant", "period_month": "2026-07-20", "target_amount": "200",
        })
        rows = client.get("/api/v1/targets?month=2026-07", headers=h).json()
        assert len(rows) == 1
        assert float(rows[0]["target_amount"]) == 200

    def test_non_manager_role_is_forbidden(self, client, db, tenant_and_user):
        """Setting the number the whole team is measured against is an
        owner/manager decision."""
        _, h = _make_user(db, _tenant_id(tenant_and_user), UserRole.RESERVATIONS)
        resp = client.put("/api/v1/targets", headers=h, json={
            "scope_type": "tenant", "period_month": "2026-07-01", "target_amount": "5",
        })
        assert resp.status_code == 403

    def test_rejects_a_property_from_another_tenant(self, client, db, tenant_and_user):
        other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other); db.commit()
        p = Property(id=str(uuid.uuid4()), tenant_id=other.id, name="Their caravan", slug="theirs", type="caravan")
        db.add(p); db.commit()

        resp = client.put("/api/v1/targets", headers=_headers(tenant_and_user), json={
            "scope_type": "property", "scope_id": p.id,
            "period_month": "2026-07-01", "target_amount": "1000",
        })
        assert resp.status_code == 404

    def test_rejects_unknown_scope_type(self, client, tenant_and_user):
        resp = client.put("/api/v1/targets", headers=_headers(tenant_and_user), json={
            "scope_type": "region", "scope_id": "x",
            "period_month": "2026-07-01", "target_amount": "1",
        })
        assert resp.status_code == 422


class TestReports:
    def test_pickup_returns_a_full_month_of_rows(self, client, tenant_and_user):
        resp = client.get("/api/v1/targets/pickup?month=2026-07", headers=_headers(tenant_and_user))
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["rows"]) == 31
        assert body["has_target"] is False   # nothing set yet, must not error

    def test_agents_and_properties_report(self, client, tenant_and_user):
        h = _headers(tenant_and_user)
        assert client.get("/api/v1/targets/agents?month=2026-07", headers=h).status_code == 200
        assert client.get("/api/v1/targets/properties?month=2026-07", headers=h).status_code == 200

    def test_scopes_lists_this_tenants_own_portfolio(self, client, db, tenant_and_user):
        """The settings screen is driven by the tenant's real properties
        and agents -- no per-client configuration."""
        tid = _tenant_id(tenant_and_user)
        db.add(Property(id=str(uuid.uuid4()), tenant_id=tid, name="Black Caravan", slug="black", type="caravan"))
        db.commit()
        _make_user(db, tid, UserRole.RESERVATIONS)

        body = client.get("/api/v1/targets/scopes", headers=_headers(tenant_and_user)).json()
        assert "Black Caravan" in [p["name"] for p in body["properties"]]
        assert len(body["agents"]) >= 1

    def test_bad_month_format_is_422(self, client, tenant_and_user):
        resp = client.get("/api/v1/targets/pickup?month=July", headers=_headers(tenant_and_user))
        assert resp.status_code == 422

    def test_requires_auth(self, client):
        assert client.get("/api/v1/targets/pickup").status_code in (401, 403)

    def test_cross_tenant_isolation(self, client, db, tenant_and_user):
        """Another tenant's target must never appear in this tenant's list."""
        other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other); db.commit()
        from app.services import targets_service
        from datetime import date
        from decimal import Decimal
        targets_service.set_target(db, other.id, "tenant", None, date(2026, 7, 1), Decimal("999999"))

        rows = client.get("/api/v1/targets?month=2026-07", headers=_headers(tenant_and_user)).json()
        assert rows == []
