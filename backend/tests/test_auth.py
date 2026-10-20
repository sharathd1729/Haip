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
    login_res = client.post("/api/v1/auth/login", json={
        "email": "sharath@testprop.com",
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
    res = client.post("/api/v1/auth/login", json={
        "email": tenant_and_user["user"].email,
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


def test_refresh_tokens_minted_together_are_all_different():
    """Refresh tokens are looked up by the hash of the token itself, so two must
    never be identical. Their only varying claim used to be an expiry with
    one-second resolution, so any two minted for the same user in the same
    second (every refresh burst mints three) were byte-for-byte the same token
    and shared one database hash -- which row a presentation matched was then
    arbitrary, and a stale but innocent token could land on a revoked twin."""
    from app.core.security import create_refresh_token

    payload = {"sub": "user-1", "tenant_id": "tenant-1", "role": "owner"}
    tokens = [create_refresh_token(payload) for _ in range(20)]

    assert len(set(tokens)) == 20
    assert len({hashlib.sha256(t.encode()).hexdigest() for t in tokens}) == 20
    for t in tokens:                       # still an ordinary, decodable refresh token
        decoded = decode_token(t)
        assert decoded["sub"] == "user-1" and decoded["type"] == "refresh"


def _rotate_twice_then_backdate(client, db, refresh, seconds_ago):
    """The old token A is rotated into B, then B is actually USED (rotated into
    C) -- proof the client received B and moved on. A's revoked_at is then
    back-dated so no test has to sleep."""
    from app.models.user import RefreshToken

    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]})
    assert r2.status_code == 200
    stored = db.query(RefreshToken).filter_by(token_hash=hashlib.sha256(refresh.encode()).hexdigest()).first()
    stored.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    db.commit()


def test_refresh_reuse_after_the_successor_was_used_revokes_family(client, tenant_and_user, db):
    """The old token turns up AFTER its successor has been used. That is not a
    lost response -- the client demonstrably received the new token and moved
    on -- so it is genuine theft: every active refresh token for that user is
    revoked, and an audit event is written."""
    from app.models.user import RefreshToken
    from app.models.audit_event import AuditEvent

    original_refresh = tenant_and_user["refresh_token"]
    user_id = tenant_and_user["user"].id

    _rotate_twice_then_backdate(client, db, original_refresh, seconds_ago=120)

    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r2.status_code == 401

    active_count = db.query(RefreshToken).filter_by(user_id=user_id, is_revoked=False).count()
    assert active_count == 0, "reuse after the successor was used must revoke that token's whole chain"

    audit_row = (
        db.query(AuditEvent)
        .filter_by(action="auth.refresh_token_reuse_detected", target_id=user_id)
        .first()
    )
    assert audit_row is not None, "genuine reuse must write an audit event"


# Real incident (Ratha, Sep 2026): the "Rathaa" login was logged out over and
# over. The backend log showed one token, issued ~20 min earlier and replaced
# ~7 min earlier, presented again and again. A rotated token's response can be
# lost (a phone backgrounded mid-request, a dropped connection), leaving the
# browser holding the old token while the new one was never used. That is not
# theft, and after 60 seconds it used to revoke every session the user had.

def test_stale_token_whose_successor_was_never_used_is_not_theft(client, tenant_and_user, db):
    """Rotated 10 minutes ago, successor never used: the client missed the
    response. It gets a fresh pair and nobody is logged out."""
    from app.models.user import RefreshToken

    original_refresh = tenant_and_user["refresh_token"]
    user_id = tenant_and_user["user"].id

    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r1.status_code == 200                       # rotated; r1's new token is never used
    stored = db.query(RefreshToken).filter_by(token_hash=hashlib.sha256(original_refresh.encode()).hexdigest()).first()
    stored.revoked_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()

    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert r2.status_code == 200, r2.text
    assert r2.json()["access_token"] and r2.json()["refresh_token"]
    assert db.query(RefreshToken).filter_by(user_id=user_id, is_revoked=False).count() >= 1

    # ...and the new pair really works: the session carries on.
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": r2.json()["refresh_token"]})
    assert r3.status_code == 200


def test_the_lost_response_tolerance_is_not_unlimited(client, tenant_and_user, db):
    """A token replaced more than a day ago is refused and treated as reuse,
    even with an unused successor."""
    from app.models.user import RefreshToken

    original_refresh = tenant_and_user["refresh_token"]
    user_id = tenant_and_user["user"].id

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh}).status_code == 200
    stored = db.query(RefreshToken).filter_by(token_hash=hashlib.sha256(original_refresh.encode()).hexdigest()).first()
    stored.revoked_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh}).status_code == 401
    assert db.query(RefreshToken).filter_by(user_id=user_id, is_revoked=False).count() == 0


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

    # Rotate A's token, use the successor too, then reuse the old one --
    # triggers reuse-detection and revokes A's family.
    _rotate_twice_then_backdate(client, db, refresh_a, seconds_ago=120)
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_a})
    assert r2.status_code == 401

    # Tenant B's user, uninvolved in A's reuse-detection event, must be unaffected.
    b_active = db.query(RefreshToken).filter_by(user_id=user_b.id, is_revoked=False).count()
    assert b_active == 1
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_b})
    assert r3.status_code == 200, "tenant B's refresh must still work after tenant A's reuse-detection"


def test_reuse_on_one_device_does_not_sign_the_user_out_elsewhere(client, tenant_and_user, db):
    """20 Oct 2026: a phone / sleeping tab presented an 8-hour-old token, which revoked EVERY session of the owner, so the
    laptop was signed out at a random moment. Now only the chain that grew out of the reused token is revoked; a separate
    login (another device) keeps working."""
    from app.core.security import create_refresh_token
    from app.models.user import RefreshToken

    user = tenant_and_user["user"]
    laptop = create_refresh_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})
    db.add(RefreshToken(id=str(uuid.uuid4()), user_id=user.id, tenant_id=user.tenant_id,
                        token_hash=hashlib.sha256(laptop.encode()).hexdigest()))
    db.commit()

    phone = tenant_and_user["refresh_token"]
    _rotate_twice_then_backdate(client, db, phone, seconds_ago=8 * 3600)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": phone}).status_code == 401

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": laptop})
    assert r.status_code == 200, "the laptop's own session must survive the phone's reuse"

