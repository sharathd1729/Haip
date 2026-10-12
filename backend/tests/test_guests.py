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
    """upsert_by_phone creates the guest once and returns the same record afterwards."""
    from app.services.guest_service import upsert_by_phone
    tenant = tenant_and_user["tenant"]

    guest1 = upsert_by_phone(db, tenant.id, "+918011111111", name="Arun Kumar")
    db.commit()
    assert guest1.id is not None
    assert guest1.phone == "+918011111111"

    guest2 = upsert_by_phone(db, tenant.id, "+918011111111")
    assert guest1.id == guest2.id


def test_guest_upsert_by_phone_is_per_tenant(db, tenant_and_user):
    """The same phone under two tenants is two guests, never one shared record."""
    import uuid as _uuid
    from app.models.tenant import Tenant
    from app.services.guest_service import upsert_by_phone

    other = Tenant(id=str(_uuid.uuid4()), name="Other", slug=f"o-{_uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    mine = upsert_by_phone(db, tenant_and_user["tenant"].id, "+918022222222", name="A")
    theirs = upsert_by_phone(db, other.id, "+918022222222", name="B")
    db.commit()

    assert mine.id != theirs.id
    assert mine.tenant_id != theirs.tenant_id


def test_guest_get_timeline(client, tenant_and_user, db):
    """GET /guests/{id}/timeline returns the (legacy) timeline object, empty for a fresh guest."""
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
    body = res.json()
    assert body["guest_id"] == guest.id
    assert body["events"] == []
    assert body["total_calls"] == 0 and body["total_stays"] == 0
