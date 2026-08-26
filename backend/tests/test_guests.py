"""Tests for guest upsert, timeline, and DPDP deletion."""

import pytest
import uuid


def test_list_guests_empty(client, tenant_and_user):
    token = tenant_and_user["access_token"]
    res = client.get("/api/v1/guests", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_list_guests_phone_filter_returns_exact_match_only(client, tenant_and_user, db):
    """Regression test: GET /guests?phone= previously had no `phone` query
    param declared at all, so FastAPI silently dropped it and the endpoint
    fell through to an unfiltered `ORDER BY created_at DESC LIMIT 1` --
    every caller (GuestPanel.tsx's per-conversation lookup) got back
    whichever guest was most recently created in the tenant, regardless of
    the phone requested. Confirmed live: every open conversation's Guest
    360 panel showed the same guest's phone number."""
    from app.models.guest import Guest
    tenant = tenant_and_user["tenant"]
    token = tenant_and_user["access_token"]

    older = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+918011110001", name="Chitra")
    db.add(older)
    db.commit()
    newer = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, phone="+918011110002", name="Sharath")
    db.add(newer)
    db.commit()

    res = client.get(
        "/api/v1/guests",
        params={"phone": "+918011110001", "limit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["phone"] == "+918011110001"
    assert rows[0]["name"] == "Chitra"


def test_guest_upsert_by_phone(db, tenant_and_user):
    """GuestService.upsert_by_phone creates or returns existing guest."""
    from app.services.guest_service import GuestService
    tenant = tenant_and_user["tenant"]

    service = GuestService(db)
    guest1 = service.upsert_by_phone(tenant_id=tenant.id, phone="+918011111111", name="Arun Kumar")
    assert guest1.id is not None
    assert guest1.phone == "+918011111111"

    # Second call returns same record
    guest2 = service.upsert_by_phone(tenant_id=tenant.id, phone="+918011111111")
    assert guest1.id == guest2.id


def test_guest_get_timeline(client, tenant_and_user, db):
    """GET /guests/{id}/timeline returns empty list for fresh guest."""
    from app.models.guest import Guest
    tenant = tenant_and_user["tenant"]
    token = tenant_and_user["access_token"]

    guest = Guest(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        phone="+918099999999",
        name="Timeline Test",
    )
    db.add(guest)
    db.commit()

    res = client.get(
        f"/api/v1/guests/{guest.id}/timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)
