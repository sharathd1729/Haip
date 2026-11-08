"""Guest add-ons (migration 194, services/guest_addons.py): what is offered (the stay property's active add-ons only,
availability for early/late/extra night), approval-first items, the signed Razorpay webhook (stay_addons + payment + ops
job, idempotent), a closed stay, public token isolation, roles and tenants. No real payment or message leaves the test."""

import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.models.guest_addons import GuestAddonOrder
from app.models.ops import OpsItem
from app.models.ops_files import OpsJob, OpsJobItem
from app.models.property import PropertyAddOn
from app.models.stay_finance import StayAddOn, StayPayment, StayPaymentLink
from app.models.user import UserRole
from app.services import booking_service as bsvc
from app.services import guest_addons as ga
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop
from tests.test_booking_detail import _connect_razorpay
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import _actor_u1, _stay, _tenant  # noqa: F401

SECRET = "whsec_addons_test"


def _addon(db, t, p, name, price, price_type="per_stay", **kw):
    a = PropertyAddOn(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        property_id=p.id,
        name=name,
        price=price,
        price_type=price_type,
        is_active=kw.pop("is_active", True),
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def _fake_link(*_a, **_k):
    return {"id": f"plink_{uuid.uuid4().hex[:12]}", "short_url": "https://rzp.io/i/test"}


@pytest.fixture()
def quiet():
    with (
        patch("app.services.payment_link_service.rzp.create_payment_link", side_effect=_fake_link),
        patch("app.services.payment_events_service._enqueue") as enq,
        patch("app.workers.tasks.ops_escalation.queue_delivery"),
    ):
        yield enq


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    stay = _stay(db, t, p)
    _connect_razorpay(db, t.id, SECRET)
    cook = _addon(db, t, p, "Private cook", 3000, "per_night", category="meal", needs_approval=True)
    bbq = _addon(db, t, p, "Poolside barbecue", 1200, "per_person", category="meal")
    early = _addon(db, t, p, "Early check-in", 2000, stay_change="early_check_in")
    night = _addon(db, t, p, "Extra night", 14500, "per_night", stay_change="extra_night", needs_approval=True)
    _addon(db, t, p, "Old item", 500, is_active=False)
    _addon(db, t, p, "Free welcome drink", 0)
    other = prop(db, t.id, "Ratha 2")
    _addon(db, t, other, "Other vehicle's decor", 4500)
    db.commit()
    link = ga.ensure_link(db, stay)
    db.commit()
    return type(
        "W",
        (),
        {
            "t": t,
            "p": p,
            "stay": stay,
            "cook": cook,
            "bbq": bbq,
            "early": early,
            "night": night,
            "token": ga.token_for(link),
            "other": other,
        },
    )()


def _webhook(client, slug, link_id, pay_id, paise):
    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": link_id, "amount_paid": paise}},
                "payment": {"entity": {"id": pay_id, "amount": paise, "method": "upi"}},
            },
        }
    ).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(f"/api/v1/webhooks/razorpay/{slug}", content=body, headers={"x-razorpay-signature": sig})


def test_offers_are_the_property_active_addons_only(db, w):
    names = {o["name"] for o in ga.offers(db, w.stay)}
    assert names == {"Private cook", "Poolside barbecue", "Early check-in", "Extra night"}
    cook = next(o for o in ga.offers(db, w.stay) if o["name"] == "Private cook")
    assert (
        cook["default_quantity"] == 3
        and cook["max_quantity"] == 3
        and cook["needs_approval"]
        and cook["unit"] == "a night"
    )


def test_unavailable_extra_night_and_early_check_in_are_not_offerable(db, w):
    _stay(db, w.t, w.p, start=6, nights=2)  # arrives on this stay's check-out day
    _stay(db, w.t, w.p, start=1, nights=2)  # leaves on this stay's check-in morning
    db.commit()
    by = {o["name"]: o for o in ga.offers(db, w.stay)}
    assert not by["Extra night"]["available"] and "arrives" in by["Extra night"]["unavailable_reason"]
    assert not by["Early check-in"]["available"] and by["Poolside barbecue"]["available"]
    with pytest.raises(Exception) as e:
        ga.place_order(db, w.stay, [{"addon_id": w.night.id, "quantity": 1}])
    assert getattr(e.value, "status_code", None) == 409


def test_cancelled_stay_gets_no_offers(client, db, w, quiet):
    w.stay.status = "cancelled"
    db.commit()
    body = client.get(f"/api/v1/public/addons/{w.token}").json()
    assert body["offers"] == [] and body["open"] is False
    r = client.post(f"/api/v1/public/addons/{w.token}/orders", json={"items": [{"addon_id": w.bbq.id, "quantity": 2}]})
    assert r.status_code == 409


def test_paid_webhook_adds_lines_payment_and_ops_job_once(client, db, w, quiet):
    r = client.post(
        f"/api/v1/public/addons/{w.token}/orders",
        json={"items": [{"addon_id": w.bbq.id, "quantity": 4}, {"addon_id": w.early.id, "quantity": 1}]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["pay"]["pay_url"] == "https://rzp.io/i/test" and r.json()["request"] is None
    order = db.query(GuestAddonOrder).filter_by(stay_id=w.stay.id).one()
    assert float(order.amount) == 6800 and order.status == "awaiting_payment"
    link = db.get(StayPaymentLink, order.payment_link_id)
    before = bsvc.financials_for(db, w.t.id, [w.stay])[w.stay.id]["total"]

    assert _webhook(client, w.t.slug, link.external_id, "pay_addon_1", 680000).status_code == 200
    assert _webhook(client, w.t.slug, link.external_id, "pay_addon_1", 680000).status_code == 200  # Razorpay retries
    db.expire_all()
    lines = db.query(StayAddOn).filter_by(stay_id=w.stay.id).all()
    assert sorted((x.name, x.quantity) for x in lines) == [("Early check-in", 1), ("Poolside barbecue", 4)]
    assert db.query(StayPayment).filter_by(external_id="pay_addon_1").count() == 1
    fin = bsvc.financials_for(db, w.t.id, [w.stay])[w.stay.id]
    assert fin["total"] == before + 6800 and fin["addons_total"] == 6800
    assert db.get(GuestAddonOrder, order.id).status == "paid"
    f = trips.ensure_file(db, w.t.id, w.stay)
    job = db.query(OpsJob).filter_by(file_id=f.id, kind="addons").one()
    assert db.query(OpsJobItem).filter_by(job_id=job.id).count() == 2
    item = db.query(OpsItem).filter_by(tenant_id=w.t.id, source_ref=f"gao-paid:{order.id}").one()
    assert item.duty == "fnb"


def test_approval_item_is_requested_then_linked_after_approval(client, db, w, quiet):
    seed_capabilities(db, w.t.id)
    foh = _user(db, w.t.id, UserRole.FOH)
    r = client.post(f"/api/v1/public/addons/{w.token}/orders", json={"items": [{"addon_id": w.cook.id, "quantity": 2}]})
    assert r.status_code == 201 and r.json()["pay"] is None
    req = r.json()["request"]
    assert req["status"] == "awaiting_approval" and req["pay_url"] is None and req["amount"] == 6000
    order = db.get(GuestAddonOrder, req["id"])
    assert db.get(OpsItem, order.ops_item_id).duty == "front_desk"

    r = client.post(f"/api/v1/ops/addon-orders/{order.id}/approve", headers=_h(foh))
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "https://rzp.io/i/test" and r.json()["order"]["status"] == "awaiting_payment"
    assert r.json()["sent"] is False  # no open WhatsApp window in the test: staff copy the link
    db.expire_all()
    assert db.get(OpsItem, order.ops_item_id).status == "resolved"
    assert client.post(f"/api/v1/ops/addon-orders/{order.id}/approve", headers=_h(foh)).status_code == 409


def test_decline_closes_the_request(client, db, w, quiet):
    seed_capabilities(db, w.t.id)
    foh = _user(db, w.t.id, UserRole.FOH)
    req = client.post(
        f"/api/v1/public/addons/{w.token}/orders", json={"items": [{"addon_id": w.night.id, "quantity": 1}]}
    ).json()["request"]
    r = client.post(f"/api/v1/ops/addon-orders/{req['id']}/decline", headers=_h(foh), json={"reason": "Booked"})
    assert r.status_code == 200 and r.json()["order"]["status"] == "declined"


def test_public_token_isolation(client, db, w, quiet):
    second = _stay(db, w.t, w.p, start=20, nights=2)
    db.commit()
    token2 = ga.token_for(ga.ensure_link(db, second))
    db.commit()
    assert token2 != w.token
    assert client.get(f"/api/v1/public/addons/{token2}").json()["check_in"] == second.check_in.isoformat()
    assert client.get("/api/v1/public/addons/not-a-real-token").status_code == 404
    # another vehicle's add-on cannot be bought through this stay's link
    other_addon = db.query(PropertyAddOn).filter_by(property_id=w.other.id).one()
    r = client.post(
        f"/api/v1/public/addons/{w.token}/orders", json={"items": [{"addon_id": other_addon.id, "quantity": 1}]}
    )
    assert r.status_code == 409
    assert "phone" not in client.get(f"/api/v1/public/addons/{w.token}").text


def test_staff_endpoints_roles_and_tenants(client, db, w, quiet):
    seed_capabilities(db, w.t.id)
    f = trips.ensure_file(db, w.t.id, w.stay)
    db.commit()
    foh, mkt = _user(db, w.t.id, UserRole.FOH), _user(db, w.t.id, UserRole.MARKETING)
    r = client.post(f"/api/v1/ops/files/{f.id}/addons/link", headers=_h(foh))
    assert r.status_code == 200 and r.json()["url"].endswith(f"/r/addons/{w.token}")
    assert client.get(f"/api/v1/ops/files/{f.id}/addons", headers=_h(foh)).json()["offer_count"] == 4
    assert client.post(f"/api/v1/ops/files/{f.id}/addons/link", headers=_h(mkt)).status_code == 403
    r = client.post(f"/api/v1/ops/files/{f.id}/addons/send", headers=_h(foh))
    assert r.status_code == 409 and "Copy the link" in r.json()["detail"]
    other = _tenant(db)
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert client.get(f"/api/v1/ops/files/{f.id}/addons", headers=_h(om)).status_code == 404
    req = client.post(
        f"/api/v1/public/addons/{w.token}/orders", json={"items": [{"addon_id": w.cook.id, "quantity": 1}]}
    ).json()["request"]
    assert client.post(f"/api/v1/ops/addon-orders/{req['id']}/approve", headers=_h(om)).status_code == 404


def test_order_query_is_tenant_scoped(db, w, quiet):
    ga.place_order(db, w.stay, [{"addon_id": w.bbq.id, "quantity": 1}])
    other = _tenant(db)
    assert db.query(GuestAddonOrder).filter_by(tenant_id=other.id).count() == 0
    assert db.query(GuestAddonOrder).filter_by(tenant_id=w.t.id).count() == 1


def test_bad_quantity_is_refused(client, db, w, quiet):
    r = client.post(f"/api/v1/public/addons/{w.token}/orders", json={"items": [{"addon_id": w.cook.id, "quantity": 9}]})
    assert r.status_code == 400 and "between 1 and 3" in r.json()["detail"]


def test_owner_sets_approval_and_stay_change_on_an_addon(client, db, w):
    seed_capabilities(db, w.t.id)
    owner = _user(db, w.t.id, UserRole.OWNER)
    url = f"/api/v1/properties/{w.p.id}/addons"
    r = client.post(
        url,
        headers=_h(owner),
        json={"name": "Late check-out", "price": 2500, "stay_change": "late_check_out", "needs_approval": True},
    )
    assert r.status_code == 201 and r.json()["stay_change"] == "late_check_out" and r.json()["needs_approval"]
    assert (
        client.post(url, headers=_h(owner), json={"name": "X", "price": 1, "stay_change": "teleport"}).status_code
        == 422
    )
    r = client.patch(f"{url}/{r.json()['id']}", headers=_h(owner), json={"stay_change": ""})
    assert r.status_code == 200 and r.json()["stay_change"] is None


def test_calendar_lists_paid_addons_without_amounts(client, db, w, quiet):
    seed_capabilities(db, w.t.id)
    db.add(
        StayAddOn(
            tenant_id=w.t.id,
            stay_id=w.stay.id,
            addon_id=w.bbq.id,
            name="Poolside barbecue",
            quantity=4,
            unit_price=1200,
            notes="Guest add-on, paid online",
        )
    )
    db.commit()
    owner = _user(db, w.t.id, UserRole.OWNER)
    d = w.stay.check_in
    r = client.get(
        f"/api/v1/calendar?from_date={d.isoformat()}&to_date={(d + timedelta(days=7)).isoformat()}", headers=_h(owner)
    )
    assert r.status_code == 200, r.text
    stays = [s for p in r.json()["properties"] for s in p["stays"] if s["id"] == w.stay.id]
    assert stays and stays[0]["addons"] == ["Poolside barbecue x4"]
