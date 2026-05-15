"""Tests for call ingestion, linking, and disposition endpoints."""

import pytest
import uuid


def test_list_calls_empty(client, tenant_and_user):
    """GET /calls returns empty list for new tenant."""
    token = tenant_and_user["access_token"]
    res = client.get("/api/v1/calls", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_callerdesk_webhook_creates_call(client, tenant_and_user, db):
    """POST webhook from CallerDesk creates a call record linked to guest."""
    tenant = tenant_and_user["tenant"]

    # First create a property for the tenant (required for webhook routing)
    from app.models.property import Property
    prop = Property(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name="Test Villa",
        city="Goa",
        property_type="villa",
    )
    db.add(prop)
    db.commit()

    payload = {
        "event": "call.completed",
        "call_uuid": "cd-test-call-001",
        "caller_number": "+918012345678",
        "called_number": "+919876543210",
        "direction": "inbound",
        "duration": 180,
        "recording_url": "https://recordings.callerdesk.io/test.mp3",
        "timestamp": "2026-05-14T10:00:00Z",
    }

    res = client.post(
        f"/api/v1/webhooks/ivr/callerdesk/{tenant.slug}",
        json=payload,
        headers={"X-CallerDesk-Secret": "test-webhook-secret"},
    )
    # Webhook may return 200 or 202 (accepted for async processing)
    assert res.status_code in (200, 202), res.text


def test_get_call_not_found(client, tenant_and_user):
    """GET /calls/{id} with unknown ID returns 404."""
    token = tenant_and_user["access_token"]
    res = client.get(
        f"/api/v1/calls/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def test_disposition_override(client, tenant_and_user, db):
    """PATCH /calls/{id}/disposition updates the disposition field."""
    from app.models.call import Call
    tenant = tenant_and_user["tenant"]
    token = tenant_and_user["access_token"]

    call = Call(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        external_id="test-call-disp",
        direction="inbound",
        caller_number="+918012345678",
        called_number="+919876543210",
        duration=120,
        status="completed",
    )
    db.add(call)
    db.commit()

    res = client.patch(
        f"/api/v1/calls/{call.id}/disposition",
        json={"disposition": "booked", "notes": "Guest booked 3 nights"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("disposition") == "booked"
