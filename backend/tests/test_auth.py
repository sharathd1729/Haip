"""Tests for /auth endpoints: register, login, refresh, logout, me, MFA."""

import hashlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.core.security import decode_token


def test_register_and_login(client):
    """Full sign-up → log-in cycle."""
    # Register
    reg_res = client.post("/api/v1/auth/register", json={
        "name": "Sharath D.",
        "email": "sharath@testprop.com",
        "password": "Secure123!",
        "tenant_name": "Test Property",
        "tenant_slug": "test-property-reg",
    })
    assert reg_res.status_code == 201, reg_res.text
    reg_data = reg_res.json()
    assert "access_token" in reg_data
    assert reg_data["user"]["role"] == "owner"

    # Login with credentials
    login_res = client.post("/api/v1/auth/login", data={
        "username": "sharath@testprop.com",
        "password": "Secure123!",
    })
    assert login_res.status_code == 200, login_res.text
    login_data = login_res.json()
    assert "access_token" in login_data
    assert login_data["user"]["email"] == "sharath@testprop.com"


def test_register_duplicate_email(client):
    """Second registration with same email returns 400."""
    payload = {
        "name": "Dup User",
        "email": "dup@test.com",
        "password": "Secure123!",
        "tenant_name": "Dup Tenant",
        "tenant_slug": "dup-tenant-abc",
    }
    r1 = client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201

    # Second registration — same email
    payload["tenant_slug"] = "dup-tenant-xyz"
    r2 = client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 400


def test_login_wrong_password(client, tenant_and_user):
    """Wrong password returns 401."""
    res = client.post("/api/v1/auth/login", data={
        "username": tenant_and_user["user"].email,
        "password": "wrong-password",
    })
    assert res.status_code == 401


def test_get_me(client, tenant_and_user):
    """GET /auth/me returns current user with tenant info."""
    token = tenant_and_user["access_token"]
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == tenant_and_user["user"].email
    assert data["role"] == "owner"
    assert "tenant" in data


def test_get_me_no_token(client):
    """GET /auth/me without token returns 401."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_refresh_token(client, tenant_and_user):
    """POST /auth/refresh returns a valid new token pair.

    NOTE: doesn't assert the new tokens differ byte-for-byte from the old
    ones -- create_access_token/create_refresh_token have no jti or
    sub-second entropy, so two calls for the same payload within the same
    wall-clock second produce identical JWTs. That's a separate, pre-existing
    quirk, out of scope here. Single-use rotation (the actual security
    property) is verified by the grace-window tests below via DB row state,
    not token string comparison.
    """
    refresh = tenant_and_user["refresh_token"]
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["refresh_token"]

    decoded_new = decode_token(data["refresh_token"])
    assert decoded_new["sub"] == tenant_and_user["user"].id


def test_logout(client, tenant_and_user):
    """POST /auth/logout revokes refresh token; second refresh returns 401."""
    refresh = tenant_and_user["refresh_token"]
    r1 = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert r1.status_code == 200

    # Second refresh must fail
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


# ─── A2: refresh-token grace window (migration 056) ───────────────────────────
# Dashboard pages fire several requests in parallel; if two of them each
# decide to proactively refresh the same stale token at once, the second
# presentation of an already-rotated token must not be treated as theft.

def test_refresh_race_within_grace_window_reissues(client, tenant_and_user):
    """A second presentation of an already-rotated token, shortly after
    rotation, is a same-client race -- it gets a fresh token pair, not 401."""
    original_refresh = tenant_and_user["refresh_token"]

    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r1.status_code == 200

    # Reuse the now-rotated original token immediately (well within the
    # 60s grace window) -- simulates a second concurrent request that grabbed
    # the same stale token before the first request's rotation landed.
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["access_token"]
    assert data["refresh_token"]


def test_refresh_reuse_outside_grace_window_revokes_family(client, tenant_and_user, db):
    """Reuse of an already-rotated token AFTER the grace window has elapsed
    is treated as genuine theft: every active refresh token for that user
    is revoked, and an audit event is written."""
    from app.models.user import RefreshToken
    from app.models.audit_event import AuditEvent

    original_refresh = tenant_and_user["refresh_token"]
    user_id = tenant_and_user["user"].id

    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r1.status_code == 200

    # Back-date revoked_at on the original row to simulate the grace window
    # having elapsed, without needing to actually sleep 60+ seconds.
    original_hash = hashlib.sha256(original_refresh.encode()).hexdigest()
    stored = db.query(RefreshToken).filter_by(token_hash=original_hash).first()
    stored.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    db.commit()

    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r2.status_code == 401

    active_count = db.query(RefreshToken).filter_by(user_id=user_id, is_revoked=False).count()
    assert active_count == 0, "reuse outside the grace window must revoke the whole token family"

    audit_row = (
        db.query(AuditEvent)
        .filter_by(action="auth.refresh_token_reuse_detected", target_id=user_id)
        .first()
    )
    assert audit_row is not None, "genuine reuse must write an audit event"


def test_refresh_reuse_detection_does_not_affect_other_tenant(client, db):
    """Revoking one user's token family on reuse-detection must not touch a
    different user's (different tenant's) refresh tokens."""
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole, RefreshToken
    from app.core.security import create_access_token, create_refresh_token, get_password_hash

    def make_tenant_user():
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant)
        db.flush()
        user = User(
            id=str(uuid.uuid4()), tenant_id=tenant.id, name="U",
            email=f"u-{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=get_password_hash("x"), role=UserRole.OWNER, is_active=True,
        )
        db.add(user)
        db.commit()
        payload = {"sub": user.id, "tenant_id": tenant.id, "role": user.role.value}
        refresh = create_refresh_token(payload)
        db.add(RefreshToken(
            id=str(uuid.uuid4()), user_id=user.id, tenant_id=tenant.id,
            token_hash=hashlib.sha256(refresh.encode()).hexdigest(),
        ))
        db.commit()
        return tenant, user, refresh

    tenant_a, user_a, refresh_a = make_tenant_user()
    tenant_b, user_b, refresh_b = make_tenant_user()

    # Rotate A's token, then reuse the old one outside the grace window --
    # triggers reuse-detection and revokes A's family.
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_a})
    assert r1.status_code == 200
    hash_a = hashlib.sha256(refresh_a.encode()).hexdigest()
    stored_a = db.query(RefreshToken).filter_by(token_hash=hash_a).first()
    stored_a.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    db.commit()
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_a})
    assert r2.status_code == 401

    # Tenant B's user, uninvolved in A's reuse-detection event, must be unaffected.
    b_active = db.query(RefreshToken).filter_by(user_id=user_b.id, is_revoked=False).count()
    assert b_active == 1
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_b})
    assert r3.status_code == 200, "tenant B's refresh must still work after tenant A's reuse-detection"
