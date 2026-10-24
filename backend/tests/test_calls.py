"""Tests for call ingestion, linking, and disposition endpoints."""

import pytest
import uuid


def test_list_calls_empty(client, tenant_and_user):
    """GET /calls returns an empty page for a new tenant."""
    token = tenant_and_user["access_token"]
    res = client.get("/api/v1/calls", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1


def _connect_callerdesk(db, tenant_id, secret="cd-secret"):
    import uuid as _uuid
    from app.core.encryption import encrypt_credentials
    from app.models.integration import Integration
    db.add(Integration(
        id=str(_uuid.uuid4()), tenant_id=tenant_id, kind="callerdesk", status="active",
        credentials_kms_blob=encrypt_credentials({"webhook_secret": secret}),
    ))
    db.commit()


def _signed(payload: dict, secret: str):
    import hashlib, hmac, json
    body = json.dumps(payload).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_callerdesk_webhook_queues_ingest_for_the_right_tenant(client, tenant_and_user, db, monkeypatch):
    """A correctly signed CallerDesk webhook is queued for ingestion under the tenant in the URL."""
    from unittest.mock import MagicMock
    tenant = tenant_and_user["tenant"]
    _connect_callerdesk(db, tenant.id)
    ingest = MagicMock()
    monkeypatch.setattr("app.api.v1.endpoints.webhooks_callerdesk.ingest_call", ingest)

    payload = {"call_id": "CD-001", "direction": "inbound", "caller_id_number": "+918012345678"}
    body, sig = _signed(payload, "cd-secret")
    res = client.post(f"/api/v1/webhooks/callerdesk/{tenant.slug}", content=body,
                      headers={"X-CallerDesk-Signature": sig, "Content-Type": "application/json"})

    assert res.status_code == 200, res.text
    assert res.json() == {"status": "queued"}
    ingest.delay.assert_called_once_with(payload=payload, tenant_id=tenant.id, ivr_provider="callerdesk")


def test_callerdesk_webhook_rejects_bad_signature(client, tenant_and_user, db, monkeypatch):
    from unittest.mock import MagicMock
    tenant = tenant_and_user["tenant"]
    _connect_callerdesk(db, tenant.id)
    ingest = MagicMock()
    monkeypatch.setattr("app.api.v1.endpoints.webhooks_callerdesk.ingest_call", ingest)

    body, _ = _signed({"call_id": "CD-002"}, "cd-secret")
    res = client.post(f"/api/v1/webhooks/callerdesk/{tenant.slug}", content=body,
                      headers={"X-CallerDesk-Signature": "0" * 64, "Content-Type": "application/json"})

    assert res.status_code == 401
    ingest.delay.assert_not_called()


def test_get_call_not_found(client, tenant_and_user):
    """GET /calls/{id} with unknown ID returns 404."""
    token = tenant_and_user["access_token"]
    res = client.get(
        f"/api/v1/calls/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def _make_call(db, tenant_id, provider="callerdesk"):
    from app.models.call import Call, CallDirection
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, ivr_provider=provider,
        ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}", direction=CallDirection.INBOUND,
        from_number="+918012345678", to_number="+919876543210", duration_seconds=120,
    )
    db.add(call)
    db.commit()
    return call


def test_disposition_override(client, tenant_and_user, db):
    """PATCH /calls/{id}/disposition records the human's disposition, note and who set it."""
    from app.models.call import CallDisposition
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    call = _make_call(db, tenant.id)

    res = client.patch(
        f"/api/v1/calls/{call.id}/disposition",
        json={"disposition": "booked", "note": "Guest booked 3 nights"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "updated", "disposition": "booked"}
    db.refresh(call)
    assert call.human_disposition == CallDisposition.BOOKED
    assert call.disposition_note == "Guest booked 3 nights"
    assert call.disposition_set_by == user.id


def test_disposition_rejects_unknown_value(client, tenant_and_user, db):
    call = _make_call(db, tenant_and_user["tenant"].id)
    res = client.patch(
        f"/api/v1/calls/{call.id}/disposition", json={"disposition": "maybe"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 400


def test_disposition_cannot_touch_another_tenants_call(client, tenant_and_user, db):
    """Cross-tenant: a call that belongs to a different tenant is a 404, never an update."""
    from app.models.call import CallDisposition
    from app.models.tenant import Tenant
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    call = _make_call(db, other.id)

    res = client.patch(
        f"/api/v1/calls/{call.id}/disposition", json={"disposition": "booked"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 404
    db.refresh(call)
    assert call.human_disposition is None


def test_uploaded_and_hand_logged_calls_stay_visible_next_to_the_active_ivr(client, tenant_and_user, db):
    """QA 25 Oct 2026: a recording uploaded on the Calls page (ivr_provider "manual") was hidden from the list AND 404'd on
    its own page for any tenant with an active IVR, because only that IVR's calls were shown. HAIP's own calls (manual,
    upload) now show; a disconnected IVR's history stays hidden; another tenant's call is still a 404."""
    from app.models.tenant import Tenant
    tenant = tenant_and_user["tenant"]
    tenant.ivr_provider = "vobiz"
    db.commit()
    auth = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    ivr, manual, upload, old = (_make_call(db, tenant.id, p) for p in ("vobiz", "manual", "upload", "mcube"))
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    foreign = _make_call(db, other.id, "manual")

    listed = {c["id"] for c in client.get("/api/v1/calls", headers=auth).json()["items"]}
    assert listed == {ivr.id, manual.id, upload.id}
    for call, code in ((manual, 200), (upload, 200), (old, 404), (foreign, 404)):
        assert client.get(f"/api/v1/calls/{call.id}", headers=auth).status_code == code
