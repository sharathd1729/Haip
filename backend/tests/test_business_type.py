"""
Signup business-type (migration 050): register() persists tenants.business_type,
and GET /workspace/context exposes it for the frontend's per-type nav gating.

Endpoint functions are called directly (not through the TestClient) so these
run locally too -- the app-level rate-limit middleware hard-blocks all /auth/*
routes when Redis is unreachable, which is why the HTTP-level register tests
in test_auth.py fail outside CI.
"""
import uuid
import pytest

from app.api.v1.endpoints.auth import register, RegisterRequest
from app.api.v1.endpoints.workspace_context import get_workspace_context
from app.models.tenant import Tenant
from app.models.user import User, UserRole


def _register_req(business_type=None):
    suffix = uuid.uuid4().hex[:8]
    return RegisterRequest(
        name="Owner",
        email=f"owner-{suffix}@test.com",
        password="testpassword123",
        tenant_name=f"Biz {suffix}",
        tenant_slug=f"biz-{suffix}",
        business_type=business_type,
    )


@pytest.mark.asyncio
async def test_register_persists_business_type(db):
    req = _register_req(business_type="caravan")
    await register(req, db)

    tenant = db.query(Tenant).filter_by(slug=req.tenant_slug).first()
    assert tenant is not None
    assert tenant.business_type == "caravan"


@pytest.mark.asyncio
async def test_register_business_type_optional(db):
    req = _register_req(business_type=None)
    await register(req, db)

    tenant = db.query(Tenant).filter_by(slug=req.tenant_slug).first()
    assert tenant is not None
    assert tenant.business_type is None


def test_register_rejects_unknown_business_type():
    with pytest.raises(Exception):  # pydantic ValidationError
        _register_req(business_type="cruise_ship")


def test_workspace_context_exposes_business_type(db):
    tenant = Tenant(
        id=str(uuid.uuid4()), name="BT Tenant", slug=f"bt-{uuid.uuid4().hex[:6]}",
        plan="growth", business_type="homestay",
    )
    db.add(tenant)
    db.flush()
    user = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@test.com", hashed_password="x",
        role=UserRole.OWNER, is_active=True,
    )
    db.add(user)
    db.commit()

    resp = get_workspace_context(db=db, current_user=user)
    assert resp.business_type == "homestay"


def test_workspace_context_business_type_isolated_per_tenant(db):
    t1 = Tenant(id=str(uuid.uuid4()), name="T1", slug=f"t1-{uuid.uuid4().hex[:6]}", plan="growth", business_type="caravan")
    t2 = Tenant(id=str(uuid.uuid4()), name="T2", slug=f"t2-{uuid.uuid4().hex[:6]}", plan="growth", business_type="hotel")
    db.add_all([t1, t2])
    db.flush()
    u2 = User(
        id=str(uuid.uuid4()), tenant_id=t2.id, name="U2",
        email=f"u2-{uuid.uuid4().hex[:6]}@test.com", hashed_password="x",
        role=UserRole.OWNER, is_active=True,
    )
    db.add(u2)
    db.commit()

    resp = get_workspace_context(db=db, current_user=u2)
    assert resp.business_type == "hotel"
