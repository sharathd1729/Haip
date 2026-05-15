"""Tests for /auth endpoints: register, login, refresh, logout, me, MFA."""

import pytest


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
    """POST /auth/refresh returns new tokens."""
    refresh = tenant_and_user["refresh_token"]
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["access_token"] != tenant_and_user["access_token"]


def test_logout(client, tenant_and_user):
    """POST /auth/logout revokes refresh token; second refresh returns 401."""
    refresh = tenant_and_user["refresh_token"]
    r1 = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert r1.status_code == 200

    # Second refresh must fail
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401
