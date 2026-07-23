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


def test_list_bookings_external_id_is_short_sequential_number(client, db):
    """external_id (what the frontend renders as "#...") should be a short
    per-tenant sequence number, not the raw UUID -- matches the shape a
    RentalWise booking already has, so #84f8dcde-... doesn't show up."""
    tenant = _make_tenant(db, "SeqTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    _make_stay(db, tenant.id, guest.id, prop.id)
    _make_stay(db, tenant.id, guest.id, prop.id)
    db.commit()

    resp = client.get("/api/v1/bookings?sort=oldest", headers=_auth(_token(user)))
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["external_id"] for r in rows] == ["1", "2"]


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


# ── GET /bookings/properties ─────────────────────────────────────────────────

def test_list_bookable_properties_includes_active_rate_plans(client, db):
    from app.models.property import RatePlan

    tenant = _make_tenant(db, "PropLookupTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id, name="White Caravan")
    rp_active = RatePlan(id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=prop.id, name="One-Day", base_price_per_night=25000, is_active=True)
    rp_inactive = RatePlan(id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=prop.id, name="Retired Package", base_price_per_night=1, is_active=False)
    db.add_all([rp_active, rp_inactive])
    db.commit()

    resp = client.get("/api/v1/bookings/properties", headers=_auth(_token(user)))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "White Caravan"
    plan_names = [p["name"] for p in body[0]["rate_plans"]]
    assert "One-Day" in plan_names
    assert "Retired Package" not in plan_names


# ── POST /bookings ────────────────────────────────────────────────────────────

def test_create_booking_happy_path_existing_guest(client, db):
    tenant = _make_tenant(db, "CreateTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id, name="Vishwas")
    db.commit()

    resp = client.post(
        "/api/v1/bookings",
        headers=_auth(_token(user)),
        json={
            "guest_id": guest.id,
            "property_id": prop.id,
            "check_in": "2026-09-01",
            "check_out": "2026-09-03",
            "adults": 4,
            "total_amount": 25000,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["main_guest"]["first_name"] == "Vishwas"
    assert body["total"] == 25000
    assert body["property"]["id"] == prop.id


def test_create_booking_new_guest_by_phone_resolves_via_identity_service(client, db):
    tenant = _make_tenant(db, "NewGuestTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    prop = _make_property(db, tenant.id)
    db.commit()

    resp = client.post(
        "/api/v1/bookings",
        headers=_auth(_token(user)),
        json={
            "guest_name": "New Guest",
            "guest_phone": "+919876543210",
            "property_id": prop.id,
            "check_in": "2026-09-10",
            "check_out": "2026-09-11",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["main_guest"]["first_name"] == "New"
    assert body["main_guest"]["last_name"] == "Guest"

    from app.models.guest_identity import GuestIdentity
    gi = db.query(GuestIdentity).filter_by(tenant_id=tenant.id, identity_type="phone", identity_value="+919876543210").first()
    assert gi is not None


def test_create_booking_defaults_total_from_rate_plan(client, db):
    from app.models.property import RatePlan

    tenant = _make_tenant(db, "RatePlanTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    rp = RatePlan(id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=prop.id, name="One-Day", base_price_per_night=25000)
    db.add(rp)
    db.commit()

    resp = client.post(
        "/api/v1/bookings",
        headers=_auth(_token(user)),
        json={
            "guest_id": guest.id,
            "property_id": prop.id,
            "rate_plan_id": rp.id,
            "check_in": "2026-09-01",
            "check_out": "2026-09-02",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["total"] == 25000


def test_create_booking_forbidden_for_concierge_role(client, db):
    tenant = _make_tenant(db, "ForbiddenTenant")
    user = _make_user(db, tenant.id, UserRole.CONCIERGE)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    db.commit()

    resp = client.post(
        "/api/v1/bookings",
        headers=_auth(_token(user)),
        json={
            "guest_id": guest.id,
            "property_id": prop.id,
            "check_in": "2026-09-01",
            "check_out": "2026-09-02",
        },
    )
    assert resp.status_code == 403


def test_create_booking_cross_tenant_property_404(client, db):
    tenant_a = _make_tenant(db, "TenantAA")
    tenant_b = _make_tenant(db, "TenantBB")
    user_b = _make_user(db, tenant_b.id, UserRole.OWNER)
    prop_a = _make_property(db, tenant_a.id)
    db.commit()

    resp = client.post(
        "/api/v1/bookings",
        headers=_auth(_token(user_b)),
        json={
            "guest_name": "X",
            "guest_phone": "+911111111111",
            "property_id": prop_a.id,
            "check_in": "2026-09-01",
            "check_out": "2026-09-02",
        },
    )
    assert resp.status_code == 404
