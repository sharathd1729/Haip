"""Tests for GET /bookings -- HAIP's own Stay records, independent of RentalWise."""
import uuid
from datetime import date

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
    # migration 071: Stay.check_in/check_out are real DATE columns -- callers
    # still pass YYYY-MM-DD strings (readable test data), parsed here.
    s = Stay(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, property_id=property_id,
        check_in=date.fromisoformat(check_in), check_out=date.fromisoformat(check_out),
        total_amount=total_amount, channel_source=channel_source,
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


# ── GET /bookings date_from/date_to ──────────────────────────────────────────

def test_list_bookings_date_range_excludes_non_overlapping_stay(client, db):
    tenant = _make_tenant(db, "DateFilterTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-08-01", check_out="2026-08-03")
    _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-09-10", check_out="2026-09-12")
    db.commit()

    resp = client.get(
        "/api/v1/bookings?date_from=2026-08-01&date_to=2026-08-31",
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["checkin"] == "2026-08-01"


def test_list_bookings_date_range_includes_stay_spanning_the_window(client, db):
    """A stay that started before date_from and ends after it (still overlaps
    the filtered window) must still show up -- not just stays strictly
    contained inside [date_from, date_to]."""
    tenant = _make_tenant(db, "SpanningTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-08-05", check_out="2026-08-20")
    db.commit()

    resp = client.get(
        "/api/v1/bookings?date_from=2026-08-10&date_to=2026-08-15",
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 1


def test_list_bookings_date_from_only(client, db):
    tenant = _make_tenant(db, "DateFromOnlyTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-07-01", check_out="2026-07-03")
    _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-09-01", check_out="2026-09-03")
    db.commit()

    resp = client.get("/api/v1/bookings?date_from=2026-08-01", headers=_auth(_token(user)))
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 1


def test_list_bookings_date_range_tenant_isolation(client, db):
    tenant_a = _make_tenant(db, "DateTenantA")
    tenant_b = _make_tenant(db, "DateTenantB")
    user_b = _make_user(db, tenant_b.id)
    prop_a = _make_property(db, tenant_a.id)
    guest_a = _make_guest(db, tenant_a.id)
    _make_stay(db, tenant_a.id, guest_a.id, prop_a.id, check_in="2026-08-01", check_out="2026-08-03")
    db.commit()

    resp = client.get(
        "/api/v1/bookings?date_from=2026-08-01&date_to=2026-08-31",
        headers=_auth(_token(user_b)),
    )
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


# ── PATCH /bookings/{id} ──────────────────────────────────────────────────────

def test_update_booking_reassigns_property(client, db):
    """The primary use case: reassigning a legacy/placeholder booking to the
    real caravan once staff know which one the guest actually used."""
    tenant = _make_tenant(db, "UpdateTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    placeholder = _make_property(db, tenant.id, name="Unassigned")
    real_caravan = _make_property(db, tenant.id, name="White Caravan")
    guest = _make_guest(db, tenant.id)
    stay = _make_stay(db, tenant.id, guest.id, placeholder.id)
    db.commit()

    resp = client.patch(
        f"/api/v1/bookings/{stay.id}",
        headers=_auth(_token(user)),
        json={"property_id": real_caravan.id},
    )
    assert resp.status_code == 200
    assert resp.json()["property"]["id"] == real_caravan.id


def test_update_booking_can_change_dates_pax_and_total(client, db):
    tenant = _make_tenant(db, "UpdateFieldsTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    stay = _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-08-01", check_out="2026-08-02", total_amount=10000)
    db.commit()

    resp = client.patch(
        f"/api/v1/bookings/{stay.id}",
        headers=_auth(_token(user)),
        json={"check_in": "2026-08-05", "check_out": "2026-08-07", "adults": 6, "total_amount": 42000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["checkin"] == "2026-08-05"
    assert body["checkout"] == "2026-08-07"
    assert body["adults"] == 6
    assert body["total"] == 42000


def test_update_booking_rejects_checkout_before_checkin(client, db):
    tenant = _make_tenant(db, "InvalidDatesTenant")
    user = _make_user(db, tenant.id, UserRole.OWNER)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    stay = _make_stay(db, tenant.id, guest.id, prop.id, check_in="2026-08-01", check_out="2026-08-02")
    db.commit()

    resp = client.patch(
        f"/api/v1/bookings/{stay.id}",
        headers=_auth(_token(user)),
        json={"check_out": "2026-07-30"},
    )
    assert resp.status_code == 422


def test_update_booking_forbidden_for_concierge_role(client, db):
    tenant = _make_tenant(db, "UpdateForbiddenTenant")
    user = _make_user(db, tenant.id, UserRole.CONCIERGE)
    prop = _make_property(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    stay = _make_stay(db, tenant.id, guest.id, prop.id)
    db.commit()

    resp = client.patch(
        f"/api/v1/bookings/{stay.id}",
        headers=_auth(_token(user)),
        json={"adults": 3},
    )
    assert resp.status_code == 403


def test_update_booking_cross_tenant_404(client, db):
    tenant_a = _make_tenant(db, "TAAA")
    tenant_b = _make_tenant(db, "TBBB")
    user_b = _make_user(db, tenant_b.id, UserRole.OWNER)
    prop_a = _make_property(db, tenant_a.id)
    guest_a = _make_guest(db, tenant_a.id)
    stay_a = _make_stay(db, tenant_a.id, guest_a.id, prop_a.id)
    db.commit()

    resp = client.patch(
        f"/api/v1/bookings/{stay_a.id}",
        headers=_auth(_token(user_b)),
        json={"adults": 3},
    )
    assert resp.status_code == 404


# ── GET /bookings?guest_id= ──────────────────────────────────────────────────

def test_list_bookings_guest_id_filter_scopes_to_one_guest(client, db):
    """Added for Profile 360's Booking section -- a guest's own stays only,
    not the tenant's whole booking list."""
    tenant = _make_tenant(db, "GuestFilterTenant")
    user = _make_user(db, tenant.id)
    prop = _make_property(db, tenant.id)
    guest_a = _make_guest(db, tenant.id, name="Guest A", phone="+919999900001")
    guest_b = _make_guest(db, tenant.id, name="Guest B", phone="+919999900002")
    _make_stay(db, tenant.id, guest_a.id, prop.id)
    _make_stay(db, tenant.id, guest_b.id, prop.id)
    db.commit()

    resp = client.get(f"/api/v1/bookings?guest_id={guest_a.id}", headers=_auth(_token(user)))
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["main_guest"]["first_name"] == "Guest"
