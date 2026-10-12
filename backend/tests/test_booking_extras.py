"""Booking page extras: payment schedule, deposit, service requests, change guest, list filters."""
import os
import uuid
from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # money endpoints sit behind bookings.read / revenue.read

from app.core.security import create_access_token  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.stay_finance import StayServiceRequest  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _d(n):
    return date.today() + timedelta(days=n)


def _setup(db, tu, total=10000, channel="direct"):
    tid = tu["tenant"].id
    prop = Property(id=gen_uuid(), tenant_id=tid, name="Caravan 1", slug=f"c-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    guest = Guest(id=gen_uuid(), tenant_id=tid, name="Asha Rao", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add_all([prop, guest])
    db.flush()
    stay = Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=_d(10), check_out=_d(12),
                adults=2, status="confirmed", total_amount=total, channel_source=channel)
    db.add(stay)
    db.commit()
    return prop, guest, stay


# ─── Payment schedule ─────────────────────────────────────────────────────────

def test_schedule_statuses_follow_payments_and_show_in_list(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    items = [
        {"label": "Advance", "amount": 3000, "due_date": _d(-2).isoformat()},      # already past
        {"label": "Balance", "amount": 7000, "due_date": _d(5).isoformat()},
    ]
    d = client.put(f"/api/v1/bookings/{stay.id}/schedule", json={"items": items}, headers=h).json()
    assert [s["status"] for s in d["schedule"]] == ["overdue", "due"]
    assert d["next_due"]["amount"] == 3000 and d["next_due"]["overdue"] is True

    row = client.get("/api/v1/bookings", headers=h).json()["data"][0]
    assert row["next_payment_due_date"] == _d(-2).isoformat() and row["payment_overdue"] is True

    d = client.post(f"/api/v1/bookings/{stay.id}/payments", json={"amount": 4000}, headers=h).json()
    assert [s["status"] for s in d["schedule"]] == ["paid", "partial"]   # 1000 of the 4000 spills onto the balance
    assert d["next_due"]["amount"] == 6000 and d["next_due"]["overdue"] is False

    d = client.post(f"/api/v1/bookings/{stay.id}/payments", json={"amount": 6000}, headers=h).json()
    assert d["next_due"] is None


def test_schedule_validation(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    url = f"/api/v1/bookings/{stay.id}/schedule"
    too_much = [{"label": "All", "amount": 10001, "due_date": _d(3).isoformat()}]
    assert client.put(url, json={"items": too_much}, headers=h).status_code == 422
    assert client.put(url, json={"items": [{"label": "x", "amount": 5, "due_date": "soon"}]}, headers=h).status_code == 422
    assert client.put(url, json={"items": [{"label": "x", "amount": 0, "due_date": _d(3).isoformat()}]}, headers=h).status_code == 422
    # clearing the plan is allowed
    assert client.put(url, json={"items": []}, headers=h).json()["schedule"] == []


# ─── Deposit ──────────────────────────────────────────────────────────────────

def test_deposit_lifecycle_does_not_touch_revenue(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    url = f"/api/v1/bookings/{stay.id}/deposit"

    d = client.put(url, json={"amount": 5000}, headers=h).json()
    assert d["deposit"]["status"] == "pending" and d["financials"]["total"] == 10000 and d["financials"]["paid"] == 0

    d = client.put(url, json={"amount": 5000, "status": "held", "method": "upi"}, headers=h).json()
    assert d["deposit"]["collected_on"] and d["financials"]["paid"] == 0       # not a payment

    d = client.put(url, json={"amount": 5000, "status": "released", "deducted": 1200}, headers=h).json()
    assert d["deposit"]["refundable"] == 3800 and d["deposit"]["resolved_on"]

    assert client.put(url, json={"amount": 5000, "status": "held", "deducted": 100}, headers=h).status_code == 422
    assert client.put(url, json={"amount": 5000, "status": "released", "deducted": 9000}, headers=h).status_code == 422
    assert client.put(url, json={"amount": 5000, "status": "melted"}, headers=h).status_code == 422

    assert client.delete(url, headers=h).json()["deposit"] is None


# ─── Service requests ─────────────────────────────────────────────────────────

def test_service_request_creates_task_and_syncs_done(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    base = f"/api/v1/bookings/{stay.id}/service-requests"
    me = tenant_and_user["user"].id

    d = client.post(base, json={"title": "Extra bed", "assigned_to": me}, headers=h).json()
    req = d["service_requests"][0]
    assert req["status"] == "open" and req["assignee_name"] == "Test Owner"
    task = db.query(Task).filter(Task.tenant_id == tenant_and_user["tenant"].id, Task.title.like("Extra bed%")).one()
    assert task.assigned_to == me and not task.is_done

    d = client.patch(f"{base}/{req['id']}", json={"status": "done"}, headers=h).json()
    assert d["service_requests"][0]["status"] == "done"
    db.refresh(task)
    assert task.is_done and task.completed_at

    client.patch(f"{base}/{req['id']}", json={"status": "open"}, headers=h)
    db.refresh(task)
    assert not task.is_done

    d = client.delete(f"{base}/{req['id']}", headers=h).json()
    assert d["service_requests"] == [] and db.query(Task).filter_by(id=task.id).first() is None


def test_service_request_rejects_foreign_assignee(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    stranger = User(id=str(uuid.uuid4()), tenant_id=other.id, name="Stranger", email=f"s-{uuid.uuid4().hex[:6]}@t.com",
                    hashed_password="x", role=UserRole.MANAGER, is_active=True)
    db.add(stranger)
    db.commit()
    r = client.post(f"/api/v1/bookings/{stay.id}/service-requests", json={"title": "x", "assigned_to": stranger.id},
                    headers=_h(tenant_and_user))
    assert r.status_code == 422


# ─── Change guest ─────────────────────────────────────────────────────────────

def test_change_guest_to_existing_by_phone_and_edit(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    other = Guest(id=gen_uuid(), tenant_id=tid, name="Ravi K", phone="+919811100022")
    db.add(other)
    db.commit()
    h = _h(tenant_and_user)
    url = f"/api/v1/bookings/{stay.id}/guest"

    d = client.patch(url, json={"guest_id": other.id}, headers=h).json()
    assert d["guest"]["id"] == other.id

    d = client.patch(url, json={"name": "Ravi Kumar", "email": "ravi@example.com"}, headers=h).json()
    assert d["guest"]["name"] == "Ravi Kumar" and d["guest"]["email"] == "ravi@example.com"
    assert client.patch(url, json={}, headers=h).status_code == 422
    assert client.patch(url, json={"name": "  "}, headers=h).status_code == 422
    assert client.patch(url, json={"guest_id": "missing"}, headers=h).status_code == 404

    d = client.patch(url, json={"phone": "+919822233344", "name": "Meera"}, headers=h).json()   # new person via identity service
    assert d["guest"]["id"] not in (other.id,) and d["guest"]["name"] == "Meera"
    assert any(e["action"] == "booking.guest_changed" for e in d["activity"])


def test_change_guest_cannot_use_other_tenants_guest(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="Someone Else", slug=f"se-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)           # guests.tenant_id is a foreign key: the other tenant has to exist
    db.flush()
    foreign = Guest(id=gen_uuid(), tenant_id=other.id, name="Z", phone="+910000000009")
    db.add(foreign)
    db.commit()
    r = client.patch(f"/api/v1/bookings/{stay.id}/guest", json={"guest_id": foreign.id}, headers=_h(tenant_and_user))
    assert r.status_code == 404


# ─── Notes + list filters + roles ─────────────────────────────────────────────

def test_concierge_notes_and_filters(client, db, tenant_and_user):
    prop, _, stay = _setup(db, tenant_and_user, channel="airbnb")
    h = _h(tenant_and_user)
    client.patch(f"/api/v1/bookings/{stay.id}", json={"concierge_notes": "Gate code 4471"}, headers=h)
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["concierge_notes"] == "Gate code 4471"

    assert client.get(f"/api/v1/bookings?property_id={prop.id}", headers=h).json()["meta"]["total"] == 1
    assert client.get("/api/v1/bookings?property_id=nope", headers=h).json()["meta"]["total"] == 0
    assert client.get("/api/v1/bookings?channel=airbnb", headers=h).json()["meta"]["total"] == 1
    assert client.get("/api/v1/bookings?channel=booking", headers=h).json()["meta"]["total"] == 0


def test_extras_forbidden_for_read_only_and_cross_tenant(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user)
    viewer = User(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, name="V", email=f"v-{uuid.uuid4().hex[:6]}@t.com",
                  hashed_password="x", role=UserRole.READ_ONLY, is_active=True)
    db.add(viewer)
    db.commit()
    vh = {"Authorization": "Bearer " + create_access_token({"sub": viewer.id, "tenant_id": viewer.tenant_id, "role": "read_only"})}
    b = f"/api/v1/bookings/{stay.id}"
    assert client.put(f"{b}/schedule", json={"items": []}, headers=vh).status_code == 403
    assert client.put(f"{b}/deposit", json={"amount": 10}, headers=vh).status_code == 403
    assert client.post(f"{b}/service-requests", json={"title": "x"}, headers=vh).status_code == 403
    assert client.patch(f"{b}/guest", json={"name": "x"}, headers=vh).status_code == 403

    t2 = Tenant(id=str(uuid.uuid4()), name="O2", slug=f"o2-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t2)
    db.flush()
    p2 = Property(id=gen_uuid(), tenant_id=t2.id, name="X", slug=f"x-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    g2 = Guest(id=gen_uuid(), tenant_id=t2.id, name="Z", phone="+910000000007")
    db.add_all([p2, g2])
    db.flush()
    s2 = Stay(id=gen_uuid(), tenant_id=t2.id, guest_id=g2.id, property_id=p2.id, check_in=_d(3), check_out=_d(4), status="confirmed")
    db.add(s2)
    db.commit()
    h = _h(tenant_and_user)
    for method, path, body in [("put", "schedule", {"items": []}), ("put", "deposit", {"amount": 10}),
                               ("post", "service-requests", {"title": "x"}), ("patch", "guest", {"name": "x"})]:
        assert getattr(client, method)(f"/api/v1/bookings/{s2.id}/{path}", json=body, headers=h).status_code == 404
