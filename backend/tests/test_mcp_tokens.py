"""Personal access token service + endpoint tests (MCP auth for Perisclaw)."""
from datetime import datetime, timedelta, timezone

from tests.conftest import *  # noqa: F401,F403

from app.services import token_service


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# ── token_service unit tests ─────────────────────────────────────────────────

def test_generate_and_verify_token(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]

    raw_token, record = token_service.generate_token(db, tenant.id, user.id, "My Token")
    assert raw_token.startswith("haip_pat_")
    assert record.token_hash != raw_token

    verified = token_service.verify_token(db, raw_token)
    assert verified is not None
    assert verified.id == record.id
    assert verified.last_used_at is not None


def test_verify_token_rejects_garbage():
    assert token_service.verify_token(None, "not-a-real-token") is None


def test_verify_token_rejects_revoked(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]

    raw_token, record = token_service.generate_token(db, tenant.id, user.id, "Revoked Token")
    ok = token_service.revoke_token(db, tenant_id=tenant.id, user_id=user.id, token_id=record.id)
    assert ok is True

    assert token_service.verify_token(db, raw_token) is None


def test_verify_token_rejects_expired(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]

    raw_token, record = token_service.generate_token(db, tenant.id, user.id, "Expiring Token")
    record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    assert token_service.verify_token(db, raw_token) is None


def test_revoke_token_scoped_to_owner(db, tenant_and_user):
    """A user can't revoke another user's token even in the same tenant."""
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]

    raw_token, record = token_service.generate_token(db, tenant.id, user.id, "Owner's Token")

    import uuid
    other_user_id = str(uuid.uuid4())
    ok = token_service.revoke_token(db, tenant_id=tenant.id, user_id=other_user_id, token_id=record.id)
    assert ok is False
    assert token_service.verify_token(db, raw_token) is not None


# ── endpoint tests ────────────────────────────────────────────────────────────

def test_create_token_endpoint_returns_raw_token_once(client, tenant_and_user):
    resp = client.post(
        "/api/v1/mcp-tokens", json={"name": "Perisclaw"},
        headers=_auth_headers(tenant_and_user["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"].startswith("haip_pat_")
    assert data["name"] == "Perisclaw"


def test_list_tokens_endpoint_never_returns_raw_token(client, tenant_and_user):
    client.post(
        "/api/v1/mcp-tokens", json={"name": "Perisclaw"},
        headers=_auth_headers(tenant_and_user["access_token"]),
    )
    resp = client.get("/api/v1/mcp-tokens", headers=_auth_headers(tenant_and_user["access_token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "token" not in data[0]
    assert "token_hash" not in data[0]


def test_revoke_token_endpoint(client, tenant_and_user):
    create_resp = client.post(
        "/api/v1/mcp-tokens", json={"name": "Perisclaw"},
        headers=_auth_headers(tenant_and_user["access_token"]),
    )
    token_id = create_resp.json()["id"]

    resp = client.delete(
        f"/api/v1/mcp-tokens/{token_id}", headers=_auth_headers(tenant_and_user["access_token"]),
    )
    assert resp.status_code == 200


def test_create_token_endpoint_requires_auth(client):
    resp = client.post("/api/v1/mcp-tokens", json={"name": "Perisclaw"})
    assert resp.status_code in (401, 403)


def test_cross_tenant_cannot_revoke_others_token(client, db, tenant_and_user):
    """A second tenant's user must not be able to revoke tenant A's token."""
    create_resp = client.post(
        "/api/v1/mcp-tokens", json={"name": "Perisclaw"},
        headers=_auth_headers(tenant_and_user["access_token"]),
    )
    token_id = create_resp.json()["id"]

    import uuid
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.core.security import create_access_token, get_password_hash

    tenant_b = Tenant(id=str(uuid.uuid4()), name="Tenant B", slug=f"tb-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant_b)
    db.flush()
    user_b = User(
        id=str(uuid.uuid4()), tenant_id=tenant_b.id, name="User B",
        email=f"userb-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("testpassword123"),
        role=UserRole.OWNER, is_active=True,
    )
    db.add(user_b)
    db.commit()
    token_b = create_access_token({"sub": user_b.id, "tenant_id": tenant_b.id, "role": user_b.role.value})

    resp = client.delete(f"/api/v1/mcp-tokens/{token_id}", headers=_auth_headers(token_b))
    assert resp.status_code == 404
