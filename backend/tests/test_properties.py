"""Tests for property CRUD endpoints."""

import pytest


def test_create_and_list_property(client, tenant_and_user):
    token = tenant_and_user["access_token"]

    # Create
    create_res = client.post(
        "/api/v1/properties",
        json={"name": "Jade Beach Villa", "city": "Goa", "property_type": "villa"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_res.status_code in (200, 201), create_res.text
    prop = create_res.json()
    assert prop["name"] == "Jade Beach Villa"
    prop_id = prop["id"]

    # List
    list_res = client.get("/api/v1/properties", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == 200
    ids = [p["id"] for p in list_res.json()]
    assert prop_id in ids


def test_update_property(client, tenant_and_user):
    token = tenant_and_user["access_token"]

    create_res = client.post(
        "/api/v1/properties",
        json={"name": "Old Name", "city": "Mumbai", "property_type": "hotel"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_res.status_code in (200, 201)
    prop_id = create_res.json()["id"]

    update_res = client.patch(
        f"/api/v1/properties/{prop_id}",
        json={"name": "Updated Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Name"


def test_tenant_isolation(client, tenant_and_user, db):
    """Properties created by tenant A are not visible to tenant B."""
    import uuid, os
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.core.security import create_access_token, get_password_hash

    # Create second tenant
    tenant_b = Tenant(id=str(uuid.uuid4()), name="Tenant B", slug=f"tenant-b-{uuid.uuid4().hex[:6]}", plan="starter")
    db.add(tenant_b)
    db.flush()
    user_b = User(
        id=str(uuid.uuid4()), tenant_id=tenant_b.id,
        name="User B", email=f"b-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pass"), role=UserRole.OWNER, is_active=True,
    )
    db.add(user_b)
    db.commit()

    token_a = tenant_and_user["access_token"]
    token_b = create_access_token({"sub": user_b.id, "tenant_id": tenant_b.id, "role": "owner"})

    # Tenant A creates a property
    r = client.post("/api/v1/properties",
        json={"name": "Private Villa A", "city": "Goa", "property_type": "villa"},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert r.status_code in (200, 201)
    prop_id = r.json()["id"]

    # Tenant B should NOT see it
    list_b = client.get("/api/v1/properties", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    ids_b = [p["id"] for p in list_b.json()]
    assert prop_id not in ids_b
