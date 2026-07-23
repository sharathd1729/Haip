"""Tests for GET /bookings -- HAIP's own Stay records, independent of RentalWise."""
import uuid

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.core.security import create_access_token, get_password_hash


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name="Test User", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_property(db, tenant_id, name="Ratha Caravan"):
    p = Property(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", type="caravan")
    db.add(p); db.flush(); return p


def _make_guest(db, tenant_id, name="Guest", phone="+919999999999"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone)
    db.add(g); db.flush(); return g


def _make_stay(db, tenant_id, guest_id, property_id, check_in="2026-08-01", check_out="2026-08-03", total_amount=15000, channel_source="direct"):
    s = Stay(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, property_id=property_id,
        check_in=check_in, check_out=check_out, total_amount=total_amount, channel_source=channel_source,
    )
    db.add(s); db.flush(); return s


def test_list_bookings_happy_path(client, db):
    tenant = _make_tenant(db, "HappyTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id, name="Vishwas")
    _make_stay(db, tenant.id, guest.id, prop.id)
    db.commit()

    resp = client.get("/api/v1/bookings", headers=_auth(_token(user)))
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["total"] == 1
    row = data["data"][0]
    assert row["main_guest"]["first_name"] == "Vishwas"
    assert row["property"]["name"] == "Ratha Caravan"
    assert row["total"] == 15000
    assert row["status"] == "confirmed"


def test_list_bookings_cross_tenant_isolation(client, db):
    tenant_a = _make_tenant(db, "TenantA")
    tenant_b = _make_tenant(db, "TenantB")
    user_b = _make_user(db, tenant_b.id)

    prop_a = _make_property(db, tenant_a.id)
    guest_a = _make_guest(db, tenant_a.id)
    _make_stay(db, tenant_a.id, guest_a.id, prop_a.id)
    db.commit()

    resp = client.get("/api/v1/bookings", headers=_auth(_token(user_b)))
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 0
