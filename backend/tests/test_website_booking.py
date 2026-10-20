"""Website booking engine: server-side prices with per-night GST slabs, holds, the paid webhook, conflicts, expiry,
enquiries, My booking, and isolation between tenants' sites."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from unittest.mock import patch

import pytest

from app.models.inquiry import Inquiry, InquirySource
from app.models.property import SeasonalRate, Stay
from app.models.stay_finance import StayInstalment, StayPayment
from app.models.task import Task
from app.models.user import UserRole
from app.models.website import BookingHold
from app.services import website_booking_service as book
from app.services import website_pricing as pricing
from tests.test_marketing_studio_content import make_user
from tests.website_fixtures import BASE, add_property, future, host_of, make_tenant, publish_live, wsite  # noqa: F401

PUB = "/api/v1/public/sites"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """The per-IP limits are middleware behaviour; these tests post many bookings from one test client."""
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


def _q(prop, ci, nights, **kw):
    return dict(check_in=ci, check_out=ci + timedelta(days=nights), adults=2, children=0, extras=[],
                today=ci - timedelta(days=5), inclusive=kw.pop("inclusive", False), gst_registered=kw.pop("gst", True),
                mode=kw.pop("mode", "instant"), deposit_percent=30, balance_due_days=7, **kw)


def test_gst_slab_is_judged_per_night(db, wsite):
    p = wsite["prop"]
    p.price_per_day = Decimal("7500")
    db.commit()
    q = pricing.quote(db, p, **_q(p, future(20), 2))
    assert q.gst_percent == Decimal("5") and q.gst == Decimal("750") and q.total == Decimal("15750")
    p.price_per_day = Decimal("7501")
    db.commit()
    q = pricing.quote(db, p, **_q(p, future(20), 1))
    assert q.gst_percent == Decimal("18") and q.total == Decimal("8851")


def test_mixed_slabs_have_no_single_gst_rate(db, wsite):
    p = wsite["prop"]
    p.price_per_day = Decimal("6000")
    ci = future(30)
    db.add(SeasonalRate(id=str(uuid.uuid4()), tenant_id=p.tenant_id, property_id=p.id, name="Peak", date_from=ci.isoformat(),
                        date_to=ci.isoformat(), price_per_night=Decimal("9000"), priority=1, is_active=True))
    db.commit()
    q = pricing.quote(db, p, **_q(p, ci, 2))
    assert [n["gst_percent"] for n in q.nights] == [Decimal("18"), Decimal("5")]
    assert q.gst_percent is None and q.gst == Decimal("1620") + Decimal("300")


def test_inclusive_tariff_and_unregistered_business(db, wsite):
    p = wsite["prop"]
    p.price_per_day = Decimal("7875")   # 7,500 + 5% inside
    db.commit()
    q = pricing.quote(db, p, **_q(p, future(20), 1, inclusive=True))
    assert q.gst_percent == Decimal("5") and q.total == Decimal("7875") and q.gst == Decimal("375")
    q = pricing.quote(db, p, **_q(p, future(20), 1, gst=False))
    assert q.gst == 0 and q.total == Decimal("7875")


def test_deposit_and_balance_due(db, wsite):
    p = wsite["prop"]
    ci = future(40)
    q = pricing.quote(db, p, **{**_q(p, ci, 3, mode="deposit"), "today": ci - timedelta(days=30)})
    assert q.pay_now == pricing.rupee(q.total * Decimal("0.30")) and q.balance == q.total - q.pay_now
    assert q.balance_due == ci - timedelta(days=7)


def test_unpriced_stay_is_price_on_request(db, wsite):
    p = add_property(db, wsite["tenant"].id, name="Hill Cottage", price=None)
    with pytest.raises(pricing.QuoteRefused) as e:
        pricing.quote(db, p, **_q(p, future(10), 2))
    assert e.value.code == "price_on_request"


# ─── holds over the public API ──────────────────────────────────────────────────────────────────────────

def _go_live(client, db, wsite, mode="instant", monkeypatch=None):
    from app.models.website import Site
    publish_live(client, wsite)          # published in the default request mode, then switched (paid modes need policies)
    site = db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one()
    site.settings = {**(site.settings or {}), "booking_mode": mode, "show_prices": True}
    db.commit()
    return site


@pytest.fixture()
def fake_rzp(monkeypatch):
    made = []
    monkeypatch.setattr("app.services.payment_link_service.razorpay_credentials", lambda db, t: {"key_id": "rzp_test", "key_secret": "s"})

    def create(key_id, key_secret, **kw):
        made.append(kw)
        return {"id": f"plink_{uuid.uuid4().hex[:10]}", "short_url": "https://rzp.io/i/test"}
    monkeypatch.setattr("app.adapters.payments.razorpay.create_payment_link", create)
    monkeypatch.setattr("app.workers.tasks.website.after_booking", type("T", (), {"delay": staticmethod(lambda *a: None)}))
    return made


def _hold_body(wsite, ci, nights=2, phone="+919812345678"):
    return {"quote": {"property_id": wsite["prop"].id, "check_in": ci.isoformat(), "check_out": (ci + timedelta(days=nights)).isoformat(),
                      "adults": 2, "children": 0, "extras": []},
            "guest": {"name": "Ananya Rao", "phone": phone, "email": "ananya@example.com", "nationality": "India"},
            "consent": {"transactional": True, "marketing": False}}


def test_public_site_is_404_until_published(client, wsite):
    assert client.get(f"{PUB}/{host_of(wsite)}/bootstrap").status_code == 404
    assert client.get(f"{PUB}/nobody.genhaip.site/bootstrap").status_code == 404


def test_instant_hold_pays_through_razorpay_and_blocks_the_dates(client, db, wsite, fake_rzp):
    _go_live(client, db, wsite)
    host = host_of(wsite)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert boot["stays"][0]["from_price"] == "4200" and boot["doc"]["pages"][0]["key"] == "home"
    ci = future(25)
    r = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "held" and out["payment_url"] == "https://rzp.io/i/test"
    assert fake_rzp[0]["amount_inr"] == float(Decimal(out["quote"]["total"]))
    assert fake_rzp[0]["callback_url"].startswith(f"https://{host}/book/done?hold=")
    again = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci + timedelta(days=1), phone="+919800000001"))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "dates_taken"
    taken = client.get(f"{PUB}/{host}/availability", params={"property_id": wsite["prop"].id, "start": ci.isoformat(), "days": 5}).json()
    assert taken["taken"] == [ci.isoformat(), (ci + timedelta(days=1)).isoformat()]
    inq = db.query(Inquiry).filter_by(tenant_id=wsite["tenant"].id, source=InquirySource.WEBSITE).one()
    assert inq.check_in == ci.isoformat() and inq.property_id == wsite["prop"].id


def test_paid_webhook_books_once_and_records_the_payment(client, db, wsite, fake_rzp):
    site = _go_live(client, db, wsite, mode="deposit")
    out = client.post(f"{PUB}/{host_of(wsite)}/holds", json=_hold_body(wsite, future(30), nights=3)).json()
    hold = db.get(BookingHold, out["hold_id"])
    pay = {"id": "pay_ABC123", "amount": int(Decimal(str(hold.pay_now)) * 100), "created_at": int(datetime.now().timestamp())}
    assert book.on_hold_link_paid(db, wsite["tenant"], hold, pay, {"id": hold.payment_link_id}) == "booked"
    assert book.on_hold_link_paid(db, wsite["tenant"], hold, pay, {"id": hold.payment_link_id}) == "duplicate"
    stays = db.query(Stay).filter_by(tenant_id=wsite["tenant"].id).all()
    assert len(stays) == 1 and stays[0].total_amount == hold.total and stays[0].inquiry_id == hold.inquiry_id
    payment = db.query(StayPayment).filter_by(stay_id=stays[0].id).one()
    assert payment.external_id == "pay_ABC123" and payment.amount == hold.pay_now
    bal = db.query(StayInstalment).filter_by(stay_id=stays[0].id).one()
    assert bal.amount == hold.total - hold.pay_now
    st = client.get(f"{PUB}/{host_of(wsite)}/holds/{hold.id}", params={"s": out["session"]}).json()
    assert st["status"] == "confirmed" and st["booking_ref"].startswith("#") and st["manage_token"]
    view = client.get(f"{PUB}/{host_of(wsite)}/manage", params={"t": st["manage_token"]}).json()
    assert Decimal(view["paid"]) == hold.pay_now and view["property"] == wsite["prop"].name
    assert client.get(f"{PUB}/{host_of(wsite)}/manage", params={"t": "x" * 40}).status_code == 404
    assert client.get(f"{PUB}/{host_of(wsite)}/holds/{hold.id}", params={"s": "w" * 30}).status_code == 404


def test_dates_taken_by_staff_meanwhile_raise_an_urgent_task_not_a_double_booking(client, db, wsite, fake_rzp):
    from app.services.booking_service import create_booking
    _go_live(client, db, wsite)
    ci = future(35)
    out = client.post(f"{PUB}/{host_of(wsite)}/holds", json=_hold_body(wsite, ci)).json()
    hold = db.get(BookingHold, out["hold_id"])
    guest_id = hold.guest_id
    create_booking(db, wsite["tenant"].id, guest_id=guest_id, prop=wsite["prop"], check_in=ci, check_out=ci + timedelta(days=1),
                   strict_stage=False)
    db.commit()
    res = book.on_hold_link_paid(db, wsite["tenant"], hold, {"id": "pay_X", "amount": 100}, {"id": hold.payment_link_id})
    assert res == "paid_conflict"
    assert db.query(Stay).filter_by(tenant_id=wsite["tenant"].id).count() == 1
    assert db.query(Task).filter(Task.tenant_id == wsite["tenant"].id, Task.title.like("URGENT%")).count() == 1


def test_request_mode_creates_a_task_and_takes_no_payment(client, db, wsite, fake_rzp):
    _go_live(client, db, wsite, mode="request")
    ci = future(45)
    r = client.post(f"{PUB}/{host_of(wsite)}/holds", json=_hold_body(wsite, ci))
    assert r.status_code == 201 and r.json()["status"] == "requested" and r.json()["payment_url"] is None
    assert fake_rzp == []
    assert db.query(Task).filter(Task.tenant_id == wsite["tenant"].id, Task.title.like("Website booking request%")).count() == 1
    other = client.post(f"{PUB}/{host_of(wsite)}/holds", json=_hold_body(wsite, ci, phone="+919800000002"))
    assert other.status_code == 201          # a request doesn't block the dates


def test_expired_holds_free_their_dates(client, db, wsite, fake_rzp):
    _go_live(client, db, wsite)
    ci = future(50)
    out = client.post(f"{PUB}/{host_of(wsite)}/holds", json=_hold_body(wsite, ci)).json()
    hold = db.get(BookingHold, out["hold_id"])
    hold.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    lapsed = book.expire_holds(db, wsite["tenant"].id)
    db.commit()
    assert [h for h, _ in lapsed] == [hold.id] and db.get(BookingHold, hold.id).status == "expired"
    assert book.is_free(db, wsite["tenant"].id, wsite["prop"], ci, ci + timedelta(days=2))


def test_quote_never_trusts_the_client_and_hides_prices_when_off(client, db, wsite, fake_rzp):
    site = _go_live(client, db, wsite)
    body = {"property_id": wsite["prop"].id, "check_in": future(20).isoformat(), "check_out": future(22).isoformat(),
            "adults": 2, "children": 0, "extras": [], "total": 1}
    assert client.post(f"{PUB}/{host_of(wsite)}/quote", json=body).status_code == 422     # unknown field refused
    body.pop("total")
    q = client.post(f"{PUB}/{host_of(wsite)}/quote", json=body).json()
    assert q["available"] is True and q["quote"]["total"] == "8400"   # no GSTIN on the invoice profile = no GST
    site.settings = {**site.settings, "show_prices": False}
    db.commit()
    q = client.post(f"{PUB}/{host_of(wsite)}/quote", json=body).json()
    assert "total" not in q["quote"]


def test_enquiry_becomes_a_website_lead_and_honeypot_is_silent(client, db, wsite):
    _go_live(client, db, wsite, mode="enquiry")
    host = host_of(wsite)
    r = client.post(f"{PUB}/{host}/enquiries", json={"name": "Rohan", "phone": "+919811112222", "message": "Diwali weekend?",
                                                    "consent": {"transactional": True, "marketing": True}})
    assert r.status_code == 201
    inq = db.query(Inquiry).filter_by(tenant_id=wsite["tenant"].id, source=InquirySource.WEBSITE).one()
    assert "Diwali weekend?" in inq.special_requests
    bot = client.post(f"{PUB}/{host}/enquiries", json={"name": "Bot", "phone": "+919800000009", "website": "http://spam"})
    assert bot.status_code == 201
    assert db.query(Inquiry).filter_by(tenant_id=wsite["tenant"].id, source=InquirySource.WEBSITE).count() == 1
    held = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, future(20)))
    assert held.status_code == 409 and held.json()["detail"]["code"] == "enquiry_only"


def test_one_sites_host_cannot_quote_another_tenants_property(client, db, wsite, fake_rzp):
    _go_live(client, db, wsite)
    other = make_tenant(db, "Rival")
    rival_prop = add_property(db, other.id, name="Rival Villa")
    body = {"property_id": rival_prop.id, "check_in": future(20).isoformat(), "check_out": future(22).isoformat(),
            "adults": 2, "children": 0, "extras": []}
    r = client.post(f"{PUB}/{host_of(wsite)}/quote", json=body)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "stay_not_found"
    assert db.query(BookingHold).filter_by(tenant_id=other.id).count() == 0


def test_placeholder_vehicles_are_never_offered(client, db, wsite):
    add_property(db, wsite["tenant"].id, name="Unassigned caravan", price=5000)
    _go_live(client, db, wsite, mode="request")
    names = [s["name"] for s in client.get(f"{PUB}/{host_of(wsite)}/bootstrap").json()["stays"]]
    assert "Unassigned caravan" not in names and wsite["prop"].name in names


def test_preview_link_shows_the_draft_and_expires(client, db, wsite):
    r = client.get(f"{BASE}/preview-link", headers=wsite["owner_h"])
    token = r.json()["url"].rsplit("/", 1)[1]
    b = client.get(f"/api/v1/public/preview/{token}/bootstrap")
    assert b.status_code == 200 and b.json()["site"]["preview"] is True
    assert client.get(f"/api/v1/public/preview/{token[:-2]}xx/bootstrap").status_code == 404
    _, mkt_h = make_user(db, wsite["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/preview-link", headers=mkt_h).status_code == 403
