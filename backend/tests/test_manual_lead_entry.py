"""Tests for POST /leads — Leads360 manual lead entry (no inbound message/
call to auto-create from)."""
import uuid
import pytest

from app.models.pipeline_stage import PipelineStage
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.consent import Consent


def _seed_stages(db, tenant_id):
    """Minimal is_default_entry / is_valid_lead_entry pair, matching the
    real tenant taxonomy's split (pipeline_stage_service._DEFAULT_TAXONOMY)."""
    unqualified = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key="unqualified", label="Unqualified",
        order=0, category="invalid", is_default_entry=True,
    )
    general = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key="general_enquiry", label="General Enquiry",
        order=1, category="valid", is_valid_lead_entry=True,
    )
    db.add_all([unqualified, general])
    db.commit()
    return unqualified, general


def test_create_manual_lead_happy_path(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    tid = tenant["id"] if isinstance(tenant, dict) else tenant.id
    _unqualified, general = _seed_stages(db, tid)

    res = client.post(
        "/api/v1/leads",
        json={
            "guest_name": "Priya Sharma",
            "phone": "+919876543210",
            "source": "walk_in",
            "adults": 4,
            "budget": 50000,
        },
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["stage_key"] == "general_enquiry"

    inquiry = db.query(Inquiry).filter_by(id=body["inquiry_id"]).first()
    assert inquiry is not None
    assert inquiry.stage_id == general.id
    assert inquiry.adults == 4
    assert float(inquiry.budget) == 50000

    guest = db.query(Guest).filter_by(id=body["guest_id"]).first()
    assert guest.name == "Priya Sharma"
    assert guest.phone == "+919876543210"

    signal = db.query(GuestIdentity).filter_by(guest_id=guest.id, identity_type="phone").first()
    assert signal is not None
    assert signal.identity_value == "+919876543210"

    # CLAUDE.md SECURITY: agent-added phone signal auto-writes DPDP consent
    consent = db.query(Consent).filter_by(guest_id=guest.id).first()
    assert consent is not None
    assert consent.source == "agent_manual"


def test_create_manual_lead_requires_phone_or_email(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    tid = tenant["id"] if isinstance(tenant, dict) else tenant.id
    _seed_stages(db, tid)

    res = client.post(
        "/api/v1/leads",
        json={"guest_name": "No Contact Info"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 422


def test_create_manual_lead_resolves_existing_guest_by_phone(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    tid = tenant["id"] if isinstance(tenant, dict) else tenant.id
    _seed_stages(db, tid)
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

    res1 = client.post(
        "/api/v1/leads",
        json={"guest_name": "Rahul K.", "phone": "+919000011111"},
        headers=headers,
    )
    assert res1.status_code == 201
    guest_id_1 = res1.json()["guest_id"]

    # Same phone again -- should resolve to the SAME guest, not a duplicate
    res2 = client.post(
        "/api/v1/leads",
        json={"guest_name": "Rahul K.", "phone": "+919000011111"},
        headers=headers,
    )
    assert res2.status_code == 201
    guest_id_2 = res2.json()["guest_id"]
    assert guest_id_1 == guest_id_2

    guests = db.query(Guest).filter_by(phone="+919000011111", tenant_id=tid).all()
    assert len(guests) == 1


def test_create_manual_lead_cross_tenant_isolation(db):
    """A lead created under tenant A must never resolve to the same guest
    as tenant B, even when the same phone number is reused -- exercised at
    the service layer directly (inquiry_service.create_manual_lead), same
    pattern as identity_service's own cross-tenant tests."""
    from app.models.tenant import Tenant
    from app.services import inquiry_service

    tenant_a = Tenant(id=str(uuid.uuid4()), name="TenantA", slug=f"a-{uuid.uuid4().hex[:6]}", plan="growth")
    tenant_b = Tenant(id=str(uuid.uuid4()), name="TenantB", slug=f"b-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add_all([tenant_a, tenant_b])
    db.flush()
    _seed_stages(db, tenant_a.id)
    _seed_stages(db, tenant_b.id)
    db.commit()

    inq_a = inquiry_service.create_manual_lead(
        db, tenant_a.id, actor_user_id=str(uuid.uuid4()),
        guest_name="Shared Phone Guest", phone="+919555566666",
    )
    inq_b = inquiry_service.create_manual_lead(
        db, tenant_b.id, actor_user_id=str(uuid.uuid4()),
        guest_name="Shared Phone Guest", phone="+919555566666",
    )

    assert inq_a.guest_id != inq_b.guest_id
    assert db.query(Guest).filter_by(id=inq_b.guest_id).first().tenant_id == tenant_b.id
