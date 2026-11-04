"""Website builder v2: a guest books and pays on a v2 (SiteSpec) site end to end, on the same hold -> Razorpay -> signed webhook
path v1 sites use. Price policy: grounded shows the website price engine's figures (from-price, rate calendar, quote);
handoff shows none and turns a paying booking mode into a request. Fake Razorpay only; nothing is sent."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import SeasonalRate, Stay
from app.models.stay_finance import StayPayment
from app.models.website import BookingHold, Site
from app.services import payment_reconcile_service as recon
from app.services import website_booking_service as book
from app.services import website_pricing as pricing
from tests.test_booking_detail import _connect_razorpay
from tests.test_website_booking import fake_rzp  # noqa: F401  (fixture)
from tests.website_fixtures import BASE, add_property, future, host_of, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"
SECRET = "whsec_test_123"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


def _spec(name="Hill Villas"):
    return {
        "spec_version": 2,
        "site": {
            "name": name,
            "contact": {"phone": "+91 98450 00000", "whatsapp": "+91 98450 00000", "address": "Madikeri"},
        },
        "tokens": {"palette": "forest-amber", "display": "fraunces", "body": "figtree"},
        "pages": [
            {
                "slug": "/",
                "title": "Home",
                "sections": [
                    {"id": "hero", "type": "hero", "variant": "split", "slots": {"headline": "Quiet villas"}},
                    {"id": "stays", "type": "stays", "variant": "cards"},
                    {"id": "book", "type": "booking", "variant": "with-rates"},
                    {"id": "contact", "type": "contact", "variant": "split"},
                ],
            }
        ],
    }


def _v2_live(client, db, w, *, mode="instant", grounded=True):
    from app.services.pipeline_stage_service import seed_default_pipeline_stages

    t = w["tenant"]
    seed_default_pipeline_stages(db, t.id)  # every real workspace has its stages (Sold = closed-won)
    t.brand_config = {**(t.brand_config or {}), "price_disclosure": "grounded" if grounded else "handoff"}
    site = db.query(Site).filter_by(tenant_id=t.id).one()
    site.settings = {**(site.settings or {}), "booking_mode": mode, "show_prices": True}
    db.commit()
    r = client.post(f"{BASE}/draft/v2", json={"spec": _spec()}, headers=w["owner_h"])
    assert r.status_code == 201, r.text
    assert next(c for c in r.json()["checks"] if c["key"] == "policies_page")["ok"]  # no longer blocks a paying site
    vid = r.json()["version"]["id"]
    p = client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=w["owner_h"])
    assert p.status_code == 200, p.text
    return host_of(w)


def _hold_body(w, ci, nights=2, phone="+919812345678"):
    return {
        "quote": {
            "property_id": w["prop"].id,
            "check_in": ci.isoformat(),
            "check_out": (ci + timedelta(days=nights)).isoformat(),
            "adults": 2,
            "children": 0,
            "extras": [],
        },
        "guest": {"name": "Ananya Rao", "phone": phone, "email": "ananya@example.com"},
        "consent": {"transactional": True, "marketing": False},
    }


def _paid(link_id, pay_id, paise):
    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": link_id, "amount_paid": paise}},
                "payment": {"entity": {"id": pay_id, "amount": paise, "method": "upi"}},
            },
        }
    ).encode()
    return body, hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_v2_guest_books_pays_and_the_dates_close(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite)
    tid, prop = wsite["tenant"].id, wsite["prop"]
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert boot["site"]["booking_mode"] == "instant" and boot["site"]["show_prices"] is True
    assert boot["bound"]["book"]["items"][0]["from"]["amount"] == "4200"  # website_pricing.from_price
    assert boot["bound"]["stays"]["items"][0]["from"]["amount"] == "4200"
    assert "cancellation_policy" in boot["policies"] or boot["policies"] == {}  # /policies page data rides along

    ci = future(20)
    avail = client.get(
        f"{PUB}/{host}/availability", params={"property_id": prop.id, "start": ci.isoformat(), "days": 3}
    ).json()
    assert avail["taken"] == [] and avail["rates"] == {(ci + timedelta(days=i)).isoformat(): "4200" for i in range(3)}
    q = client.post(f"{PUB}/{host}/quote", json=_hold_body(wsite, ci)["quote"]).json()
    assert q["available"] and q["mode"] == "instant" and q["quote"]["total"] == "8400"

    out = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci))
    assert out.status_code == 201, out.text
    out = out.json()
    assert out["status"] == "held" and out["payment_url"] and fake_rzp[0]["amount_inr"] == 8400.0
    assert fake_rzp[0]["callback_url"].startswith(f"https://{host}/book/done?hold=")  # the sites app's /book/done page
    second = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci, phone="+919800000001"))
    assert (
        second.status_code == 409 and second.json()["detail"]["code"] == "dates_taken"
    )  # held while the first guest pays

    _connect_razorpay(db, tid, SECRET)
    hold = db.get(BookingHold, out["hold_id"])
    url = f"/api/v1/webhooks/razorpay/{wsite['tenant'].slug}"
    body, sig = _paid(hold.payment_link_id, "pay_V2A", 840000)
    assert client.post(url, content=body, headers={"x-razorpay-signature": "deadbeef"}).status_code == 401
    assert db.query(Stay).filter_by(tenant_id=tid).count() == 0
    with patch("app.workers.tasks.website.after_booking.delay") as confirm:  # guest messages: queued, never sent here
        assert client.post(url, content=body, headers={"x-razorpay-signature": sig}).json()["status"] == "booked"
        assert client.post(url, content=body, headers={"x-razorpay-signature": sig}).json()["status"] == "duplicate"
    assert confirm.call_count == 1

    stay = db.query(Stay).filter_by(tenant_id=tid).one()
    assert stay.status == "confirmed" and stay.check_in == ci and stay.total_amount == Decimal("8400")
    pay = db.query(StayPayment).filter_by(stay_id=stay.id).one()
    assert pay.external_id == "pay_V2A" and pay.amount == Decimal("8400")
    inq = db.get(Inquiry, hold.inquiry_id)
    assert stay.inquiry_id == inq.id
    assert db.get(PipelineStage, inq.stage_id).is_closed_won  # the lead is Sold
    st = client.get(f"{PUB}/{host}/holds/{hold.id}", params={"s": out["session"]}).json()
    assert st["status"] == "confirmed" and st["manage_token"]

    avail = client.get(
        f"{PUB}/{host}/availability", params={"property_id": prop.id, "start": ci.isoformat(), "days": 3}
    ).json()
    assert avail["taken"] == [ci.isoformat(), (ci + timedelta(days=1)).isoformat()]
    fake_rzp.clear()
    later = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci + timedelta(days=1), phone="+919800000002"))
    assert later.status_code == 409 and fake_rzp == []  # booked: nobody else can pay for it


def test_v2_handoff_shows_no_price_and_takes_a_request_not_a_payment(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite, mode="instant", grounded=False)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert boot["site"]["booking_mode"] == "request" and boot["site"]["show_prices"] is False
    assert boot["bound"]["book"]["items"][0]["from"] is None and boot["bound"]["stays"]["items"][0]["from"] is None
    ci = future(22)
    avail = client.get(
        f"{PUB}/{host}/availability", params={"property_id": wsite["prop"].id, "start": ci.isoformat()}
    ).json()
    assert "rates" not in avail
    q = client.post(f"{PUB}/{host}/quote", json=_hold_body(wsite, ci)["quote"]).json()
    assert q["mode"] == "request" and "total" not in q["quote"] and "nights" not in q["quote"]
    r = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci))
    assert r.status_code == 201 and r.json()["status"] == "requested" and r.json()["payment_url"] is None
    assert fake_rzp == []  # no payment link, no figure


def test_v2_rate_calendar_follows_seasonal_rates_and_marks_sold_out_dates(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite)
    prop, ci = wsite["prop"], future(30)
    db.add(
        SeasonalRate(
            tenant_id=prop.tenant_id,
            property_id=prop.id,
            name="Peak",
            date_from=(ci + timedelta(days=1)).isoformat(),
            date_to=(ci + timedelta(days=1)).isoformat(),
            price_per_night=Decimal("6500"),
            is_active=True,
        )
    )
    db.commit()
    rates = pricing.rate_calendar(db, prop, ci, ci + timedelta(days=3))
    assert rates == {
        ci.isoformat(): "4200",
        (ci + timedelta(days=1)).isoformat(): "6500",
        (ci + timedelta(days=2)).isoformat(): "4200",
    }
    q = client.post(f"{PUB}/{host}/quote", json=_hold_body(wsite, ci)["quote"]).json()
    assert q["quote"]["total"] == "10700"  # the quote agrees with the calendar
    client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci))
    avail = client.get(
        f"{PUB}/{host}/availability", params={"property_id": prop.id, "start": ci.isoformat(), "days": 3}
    ).json()
    assert avail["taken"] == [ci.isoformat(), (ci + timedelta(days=1)).isoformat()]


def test_v2_expired_hold_frees_the_dates_for_the_next_guest(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite)
    ci = future(40)
    out = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci)).json()
    assert client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci, phone="+919800000003")).status_code == 409
    hold = db.get(BookingHold, out["hold_id"])
    hold.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert [h for h, _ in book.expire_holds(db, wsite["tenant"].id)] == [hold.id]
    db.commit()
    nxt = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, ci, phone="+919800000003"))
    assert nxt.status_code == 201 and nxt.json()["status"] == "held"


def test_a_lost_webhook_is_recovered_by_reconcile_once(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite, mode="deposit")
    _connect_razorpay(db, wsite["tenant"].id, SECRET)
    out = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, future(45))).json()
    hold = db.get(BookingHold, out["hold_id"])
    paise = int(Decimal(str(hold.pay_now)) * 100)

    def remote(k, s, link_id):
        return {
            "id": link_id,
            "status": "paid",
            "amount_paid": paise,
            "payments": [{"payment_id": "pay_LOST", "amount": paise, "method": "upi", "status": "captured"}],
        }

    with patch("app.workers.tasks.website.after_booking.delay"):
        assert recon.reconcile_tenant(db, wsite["tenant"], fetch=remote) == {"checked": 1, "booked": 1}
        assert recon.reconcile_tenant(db, wsite["tenant"], fetch=remote) == {"checked": 0}  # confirmed: not asked again
    stay = db.query(Stay).filter_by(tenant_id=wsite["tenant"].id).one()
    assert db.query(StayPayment).filter_by(stay_id=stay.id, external_id="pay_LOST").count() == 1


def test_v2_site_offers_only_its_chosen_stays_and_another_tenant_cannot_read_its_rates(client, db, wsite, fake_rzp):  # noqa: F811
    hidden = add_property(db, wsite["tenant"].id, name="Barn Loft")
    site = db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one()
    site.settings = {**(site.settings or {}), "property_ids": [wsite["prop"].id]}
    db.commit()
    host = _v2_live(client, db, wsite)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert [i["id"] for i in boot["bound"]["book"]["items"]] == [wsite["prop"].id]
    assert [i["id"] for i in boot["bound"]["stays"]["items"]] == [wsite["prop"].id]
    assert client.get(f"{PUB}/{host}/availability", params={"property_id": hidden.id}).status_code == 404

    other = make_tenant(db, "Elsewhere")
    theirs = add_property(db, other.id, name="Sea Hut")
    assert client.get(f"{PUB}/{host}/availability", params={"property_id": theirs.id}).status_code == 404
    body = _hold_body(wsite, future(25))
    body["quote"]["property_id"] = theirs.id
    assert client.post(f"{PUB}/{host}/quote", json=body["quote"]).status_code == 404
    assert client.post(f"{PUB}/{host}/holds", json=body).status_code == 404
