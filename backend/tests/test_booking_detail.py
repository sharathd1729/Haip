"""Booking detail page API: add-ons, payment ledger, conflicts, Razorpay link + webhook."""
import hashlib
import hmac
import json
import os
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import encrypt_credentials  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.property import BlockedDate, Property, PropertyAddOn, Stay  # noqa: E402
from app.models.stay_finance import StayPayment, StayPaymentLink  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _d(n):
    return date.today() + timedelta(days=n)


def _setup(db, tu, total=10000):
    tid = tu["tenant"].id
    prop = Property(id=gen_uuid(), tenant_id=tid, name="Caravan 1", slug=f"c-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    guest = Guest(id=gen_uuid(), tenant_id=tid, name="Asha Rao", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add_all([prop, guest])
    db.flush()
    stay = Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=_d(10), check_out=_d(12),
                adults=2, status="confirmed", total_amount=total, channel_source="direct")
    db.add(stay)
    db.commit()
    return prop, guest, stay


def test_detail_shape_and_money_start_at_zero_paid(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    r = client.get(f"/api/v1/bookings/{stay.id}", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nights"] == 2 and d["guest"]["name"] == "Asha Rao" and d["property"]["name"] == "Caravan 1"
    f = d["financials"]
    assert (f["total"], f["paid"], f["outstanding"], f["payment_status"]) == (10000, 0, 10000, "unpaid")


def test_catalog_and_custom_addons_change_total(client, db, tenant_and_user):
    prop, _, stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    cat = PropertyAddOn(id=gen_uuid(), tenant_id=tid, property_id=prop.id, name="Bonfire", price=500, price_type="per_night", is_active=True)
    db.add(cat)
    db.commit()
    h = _h(tenant_and_user)

    d = client.post(f"/api/v1/bookings/{stay.id}/addons", json={"addon_id": cat.id}, headers=h).json()
    assert d["addons"][0]["quantity"] == 2 and d["financials"]["addons_total"] == 1000     # per_night x 2 nights
    d = client.post(f"/api/v1/bookings/{stay.id}/addons", json={"name": "Cake", "unit_price": 800}, headers=h).json()
    assert d["financials"]["total"] == 11800

    line = d["addons"][0]["id"]
    d = client.patch(f"/api/v1/bookings/{stay.id}/addons/{line}", json={"quantity": 1}, headers=h).json()
    assert d["financials"]["addons_total"] == 1300
    d = client.delete(f"/api/v1/bookings/{stay.id}/addons/{line}", headers=h).json()
    assert [a["name"] for a in d["addons"]] == ["Cake"]


def test_addon_from_other_property_rejected(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    other = Property(id=gen_uuid(), tenant_id=tid, name="Villa 2", slug=f"v-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    db.add(other)
    db.flush()
    cat = PropertyAddOn(id=gen_uuid(), tenant_id=tid, property_id=other.id, name="Chef", price=900, is_active=True)
    db.add(cat)
    db.commit()
    assert client.post(f"/api/v1/bookings/{stay.id}/addons", json={"addon_id": cat.id}, headers=_h(tenant_and_user)).status_code == 404


def test_payment_ledger_statuses_and_refund_guard(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    url = f"/api/v1/bookings/{stay.id}/payments"

    d = client.post(url, json={"amount": 4000, "method": "upi", "reference": "UTR1"}, headers=h).json()
    assert d["financials"]["payment_status"] == "partial" and d["financials"]["outstanding"] == 6000
    d = client.post(url, json={"amount": 6000, "method": "cash"}, headers=h).json()
    assert d["financials"]["payment_status"] == "paid" and d["financials"]["outstanding"] == 0

    assert client.post(url, json={"kind": "refund", "amount": 99999}, headers=h).status_code == 422
    d = client.post(url, json={"kind": "refund", "amount": 2000, "method": "upi"}, headers=h).json()
    assert d["financials"]["paid"] == 8000 and d["financials"]["payment_status"] == "partial"

    pid = d["payments"][0]["id"]
    d = client.delete(f"{url}/{pid}", headers=h).json()
    assert len(d["payments"]) == 2
    assert client.post(url, json={"amount": 0}, headers=h).status_code == 422
    assert client.post(url, json={"amount": 10, "method": "bitcoin"}, headers=h).status_code == 422


def test_list_reports_real_money_and_filters(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    row = client.get("/api/v1/bookings", headers=h).json()["data"][0]
    assert row["payment_status"] == "unpaid" and row["total_paid"] == 0 and row["total_outstanding"] == 10000

    client.post(f"/api/v1/bookings/{stay.id}/payments", json={"amount": 3000}, headers=h)
    assert client.get("/api/v1/bookings?payment_status=partial", headers=h).json()["meta"]["total"] == 1
    assert client.get("/api/v1/bookings?payment_status=unpaid", headers=h).json()["meta"]["total"] == 0
    client.post(f"/api/v1/bookings/{stay.id}/payments", json={"amount": 7000}, headers=h)
    assert client.get("/api/v1/bookings?payment_status=paid", headers=h).json()["meta"]["total"] == 1
    assert client.get("/api/v1/bookings?payment_status=weird", headers=h).status_code == 422


def test_patch_blocks_overlap_unless_forced_and_audits(client, db, tenant_and_user):
    prop, guest, stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    db.add(BlockedDate(tenant_id=tid, property_id=prop.id, blocked_from=_d(20).isoformat(), blocked_to=_d(23).isoformat(),
                       reason="maintenance", is_active=True))
    db.commit()
    h = _h(tenant_and_user)
    move = {"check_in": _d(20).isoformat(), "check_out": _d(22).isoformat()}

    r = client.patch(f"/api/v1/bookings/{stay.id}", json=move, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "date_conflict"

    assert client.patch(f"/api/v1/bookings/{stay.id}", json={**move, "force": True}, headers=h).status_code == 200
    d = client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()
    assert d["check_in"] == move["check_in"]
    assert any(e["action"] == "booking.updated" and e["payload"]["forced"] for e in d["activity"])


def test_patch_front_desk_fields(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    r = client.patch(f"/api/v1/bookings/{stay.id}", json={"check_in_time": "14:00", "internal_notes": "Late arrival"}, headers=h)
    assert r.status_code == 200
    d = client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()
    assert d["check_in_time"] == "14:00" and d["internal_notes"] == "Late arrival"
    assert client.patch(f"/api/v1/bookings/{stay.id}", json={"check_in_time": "25:99"}, headers=h).status_code == 422
    assert client.patch(f"/api/v1/bookings/{stay.id}", json={"status": "teleported"}, headers=h).status_code == 422
    client.patch(f"/api/v1/bookings/{stay.id}", json={"check_in_time": ""}, headers=h)
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["check_in_time"] is None


def test_forbidden_role_and_cross_tenant(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    viewer = User(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, name="V", email=f"v-{uuid.uuid4().hex[:6]}@t.com",
                  hashed_password="x", role=UserRole.READ_ONLY, is_active=True)
    db.add(viewer)
    db.commit()
    vh = {"Authorization": "Bearer " + create_access_token({"sub": viewer.id, "tenant_id": viewer.tenant_id, "role": "read_only"})}
    assert client.post(f"/api/v1/bookings/{stay.id}/payments", json={"amount": 5}, headers=vh).status_code == 403
    assert client.post(f"/api/v1/bookings/{stay.id}/addons", json={"name": "x", "unit_price": 1}, headers=vh).status_code == 403

    # a booking of another tenant is a 404 for everything
    from app.models.tenant import Tenant
    t2 = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t2)
    db.flush()
    p2 = Property(id=gen_uuid(), tenant_id=t2.id, name="X", slug=f"x-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    g2 = Guest(id=gen_uuid(), tenant_id=t2.id, name="Z", phone="+910000000001")
    db.add_all([p2, g2])
    db.flush()
    s2 = Stay(id=gen_uuid(), tenant_id=t2.id, guest_id=g2.id, property_id=p2.id, check_in=_d(3), check_out=_d(4), status="confirmed")
    db.add(s2)
    db.commit()
    h = _h(tenant_and_user)
    assert client.get(f"/api/v1/bookings/{s2.id}", headers=h).status_code == 404
    assert client.post(f"/api/v1/bookings/{s2.id}/payments", json={"amount": 5}, headers=h).status_code == 404
    assert client.post(f"/api/v1/bookings/{s2.id}/payment-links", json={}, headers=h).status_code == 404


# ─── Razorpay ─────────────────────────────────────────────────────────────────

def _connect_razorpay(db, tid, webhook_secret="whsec_test_123"):
    db.add(Integration(tenant_id=tid, kind="razorpay", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"key_id": "rzp_test_abc12345", "key_secret": "s3cretvalue", "webhook_secret": webhook_secret})))
    db.commit()


def test_connect_validates_keys_and_returns_webhook(client, db, tenant_and_user):
    h = _h(tenant_and_user)
    assert client.post("/api/v1/payments/razorpay/connect", json={"key_id": "nope12345", "key_secret": "x" * 10}, headers=h).status_code == 422
    with patch("app.api.v1.endpoints.payments_razorpay.rzp.check_credentials"):
        r = client.post("/api/v1/payments/razorpay/connect", json={"key_id": "rzp_test_abc12345", "key_secret": "s3cretvalue"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    slug = tenant_and_user["tenant"].slug
    assert body["mode"] == "test" and body["webhook_url"].endswith(f"/webhooks/razorpay/{slug}") and body["webhook_secret"]
    st = client.get("/api/v1/payments/razorpay", headers=h).json()
    assert st["connected"] and "webhook_secret" not in st and "key_secret" not in json.dumps(st)
    assert client.delete("/api/v1/payments/razorpay", headers=h).status_code == 204
    assert client.get("/api/v1/payments/razorpay", headers=h).json() == {"connected": False}


def test_payment_link_needs_connection_then_creates(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    assert client.post(f"/api/v1/bookings/{stay.id}/payment-links", json={}, headers=h).status_code == 422

    _connect_razorpay(db, tenant_and_user["tenant"].id)
    captured = {}

    def fake(key_id, key_secret, **kw):
        captured.update(kw)
        return {"id": "plink_abc123", "short_url": "https://rzp.io/i/abc"}
    with patch("app.api.v1.endpoints.booking_detail.rzp.create_payment_link", side_effect=fake):
        r = client.post(f"/api/v1/bookings/{stay.id}/payment-links", json={"amount": 2500}, headers=h)
    assert r.status_code == 201 and r.json()["short_url"] == "https://rzp.io/i/abc"
    assert captured["amount_inr"] == 2500 and captured["notes"]["haip_stay_id"] == stay.id


def _signed(payload: dict, secret: str):
    body = json.dumps(payload).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _paid_event(link_id, pay_id, paise=250000):
    return {"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"id": link_id, "amount_paid": paise}},
        "payment": {"entity": {"id": pay_id, "amount": paise, "method": "upi"}}}}


def test_webhook_records_payment_once_and_rejects_bad_signature(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    tid, slug = tenant_and_user["tenant"].id, tenant_and_user["tenant"].slug
    _connect_razorpay(db, tid)
    db.add(StayPaymentLink(tenant_id=tid, stay_id=stay.id, provider="razorpay", external_id="plink_1", short_url="https://rzp.io/i/1",
                           amount=2500, status="created"))
    db.commit()
    url = f"/api/v1/webhooks/razorpay/{slug}"

    body, sig = _signed(_paid_event("plink_1", "pay_1"), "whsec_test_123")
    assert client.post(url, content=body, headers={"x-razorpay-signature": "deadbeef"}).status_code == 401
    assert client.post(url, content=body).status_code == 401
    wrong, wsig = _signed(_paid_event("plink_1", "pay_1"), "some-other-secret")
    assert client.post(url, content=wrong, headers={"x-razorpay-signature": wsig}).status_code == 401
    assert db.query(StayPayment).filter_by(stay_id=stay.id).count() == 0

    assert client.post(url, content=body, headers={"x-razorpay-signature": sig}).json()["status"] == "recorded"
    assert client.post(url, content=body, headers={"x-razorpay-signature": sig}).json()["status"] == "duplicate"   # Razorpay retries
    pays = db.query(StayPayment).filter_by(stay_id=stay.id).all()
    assert len(pays) == 1 and float(pays[0].amount) == 2500 and pays[0].method == "razorpay"
    assert db.query(StayPaymentLink).filter_by(external_id="plink_1").first().status == "paid"
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=_h(tenant_and_user)).json()["financials"]["paid"] == 2500


def test_webhook_unknown_tenant_and_unknown_link(client, db, tenant_and_user):
    assert client.post("/api/v1/webhooks/razorpay/no-such-tenant", content=b"{}").status_code == 404
    tid, slug = tenant_and_user["tenant"].id, tenant_and_user["tenant"].slug
    _connect_razorpay(db, tid)
    body, sig = _signed(_paid_event("plink_unknown", "pay_9"), "whsec_test_123")
    r = client.post(f"/api/v1/webhooks/razorpay/{slug}", content=body, headers={"x-razorpay-signature": sig})
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_gateway_payment_cannot_be_deleted(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    p = StayPayment(tenant_id=tid, stay_id=stay.id, kind="payment", amount=100, method="razorpay", external_id="pay_x", paid_on=date.today())
    db.add(p)
    db.commit()
    assert client.delete(f"/api/v1/bookings/{stay.id}/payments/{p.id}", headers=_h(tenant_and_user)).status_code == 409
