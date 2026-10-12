"""Quick filters on GET /bookings: when=upcoming|current|past and needs_property."""
import uuid
from datetime import date, timedelta

import pytest

from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.property import Property, Stay

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # money endpoints sit behind bookings.read / revenue.read


def _h(ctx):
    return {"Authorization": f"Bearer {ctx['access_token']}"}


def _prop(db, tid, name):
    p = Property(id=gen_uuid(), tenant_id=tid, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    db.add(p)
    db.flush()
    return p


def _stay(db, tid, prop, guest, start_off, end_off, status="confirmed"):
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id,
             check_in=date.today() + timedelta(days=start_off), check_out=date.today() + timedelta(days=end_off),
             status=status, total_amount=25000, channel_source="direct")
    db.add(s)
    return s


def test_when_filters_split_upcoming_current_and_past(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid, "Caravan 1")
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone="+919876543210")
    db.add(g); db.flush()
    upcoming = _stay(db, tid, prop, g, 5, 7)
    cancelled_future = _stay(db, tid, prop, g, 9, 10, status="cancelled")
    current = _stay(db, tid, prop, g, -1, 2, status="checked_in")
    past = _stay(db, tid, prop, g, -9, -7, status="checked_out")
    db.commit()

    def ids(when):
        r = client.get("/api/v1/bookings", params={"when": when}, headers=_h(tenant_and_user))
        assert r.status_code == 200
        return {b["id"] for b in r.json()["data"]}

    assert ids("upcoming") == {upcoming.id}            # cancelled future stays are not "upcoming"
    assert ids("current") == {current.id}
    assert ids("past") == {past.id}
    assert client.get("/api/v1/bookings", params={"when": "someday"}, headers=_h(tenant_and_user)).status_code == 422


def test_needs_property_lists_only_placeholder_property_bookings_of_this_tenant(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    real = _prop(db, tid, "Caravan 1")
    placeholder = _prop(db, tid, "Unassigned (legacy bookings -- reassign manually)")
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone="+919876543210")
    db.add(g); db.flush()
    _stay(db, tid, real, g, 3, 4)
    legacy = _stay(db, tid, placeholder, g, 5, 6)

    # Another workspace with the same placeholder name must never leak in.
    from app.models.tenant import Tenant
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    other_prop = _prop(db, other.id, "Unassigned (legacy)")
    og = Guest(id=gen_uuid(), tenant_id=other.id, name="Zed", phone="+919000000000")
    db.add(og); db.flush()
    _stay(db, other.id, other_prop, og, 3, 4)
    db.commit()

    r = client.get("/api/v1/bookings", params={"needs_property": "true"}, headers=_h(tenant_and_user))
    assert r.status_code == 200
    assert {b["id"] for b in r.json()["data"]} == {legacy.id}


def test_payment_status_due_means_money_still_owed_and_skips_cancelled(client, db, tenant_and_user):
    from app.models.stay_finance import StayPayment
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid, "Caravan 1")
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone="+919876543210")
    db.add(g); db.flush()
    unpaid = _stay(db, tid, prop, g, 3, 4)
    cancelled = _stay(db, tid, prop, g, 6, 7, status="cancelled")
    paid = _stay(db, tid, prop, g, 9, 10)
    db.flush()
    db.add(StayPayment(id=gen_uuid(), tenant_id=tid, stay_id=paid.id, kind="payment", amount=25000, method="upi", paid_on=date.today()))
    db.commit()
    r = client.get("/api/v1/bookings", params={"payment_status": "due"}, headers=_h(tenant_and_user))
    assert r.status_code == 200
    assert {b["id"] for b in r.json()["data"]} == {unpaid.id}
