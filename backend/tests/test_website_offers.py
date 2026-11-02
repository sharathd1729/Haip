"""Website phase 4: starting designs per business type, promo codes (checked + applied server-side, GST on the
discounted rate, Razorpay amount follows, cap counted on paid bookings, audited), and the seasonal offer band."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.user import UserRole
from app.models.website import BookingHold, WebsitePromoCode
from app.services import website_autobuild, website_pricing, website_starters
from app.services.website_seo import KINDS
from tests.test_marketing_studio_content import make_user
from tests.test_website_booking import fake_rzp  # noqa: F401  (fixture)
from tests.test_website_v2_booking import SECRET, _hold_body, _paid, _spec, _v2_live
from tests.website_fixtures import BASE, future, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_has_a_valid_starter(client, db, wsite, kind):  # noqa: F811
    assert website_starters.starter_for(kind) is not None
    wsite["tenant"].business_type = kind
    db.commit()
    spec = website_autobuild.spec_for(db, wsite["tenant"])  # validated by SiteSpec inside
    st = website_starters.STARTERS[kind]
    assert (
        spec["tokens"]["palette"]["name"] == st["tokens"]["palette"]
        and spec["tokens"]["display"] == st["tokens"]["display"]
    )
    assert spec["pages"][0]["sections"][0]["variant"] == st["hero"]


def test_caravan_starter_puts_trips_first_and_unknown_type_keeps_default():
    secs = [{"id": i, "type": "x", "variant": "v", "slots": {}} for i in ("stays", "book", "packages", "gallery")]
    out, st = website_starters.apply(secs, "caravan")
    assert [s["id"] for s in out] == ["packages", "stays", "book", "gallery"] and out[0]["slots"][
        "heading"
    ] == "Pick your trip"
    assert website_starters.apply(secs, None) == (secs, None)


def _promo(client, w, **kw):
    body = {"code": "monsoon15", "kind": "percent", "value": 15, **kw}
    return client.post(f"{BASE}/promos", json=body, headers=w["owner_h"])


def test_promo_roles_validation_and_tenant_isolation(client, db, wsite):  # noqa: F811
    r = _promo(client, wsite)
    assert r.status_code == 201 and r.json()["code"] == "MONSOON15"
    assert _promo(client, wsite).status_code == 409
    assert _promo(client, wsite, code="BIG", value=95).status_code == 422
    assert (
        client.post(
            f"{BASE}/promos", json={"code": "X1Y2", "kind": "flat", "value": 500}, headers=wsite["mkt_h"]
        ).status_code
        == 403
    )
    assert client.get(f"{BASE}/promos", headers=wsite["mkt_h"]).status_code == 200
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/promos", headers=other_h).json() == []
    pid = r.json()["id"]
    assert (
        client.put(
            f"{BASE}/promos/{pid}", json={"code": "HACK", "kind": "flat", "value": 1}, headers=other_h
        ).status_code
        == 404
    )
    assert db.query(AuditEvent).filter_by(tenant_id=wsite["tenant"].id, action="website.promo_created").count() == 1


def test_discount_lowers_nights_gst_and_payment(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite)
    _promo(client, wsite, min_nights=2)
    body = _hold_body(wsite, future(25))
    plain = client.post(f"{PUB}/{host}/quote", json=body["quote"]).json()["quote"]
    q = client.post(f"{PUB}/{host}/quote", json={**body["quote"], "promo_code": "monsoon15"}).json()["quote"]
    assert plain["total"] == "8400" and q["promo_code"] == "MONSOON15" and q["discount"] == "1260"
    assert q["total"] == "7140" and q["nights"][0]["rate"] == "3570"
    short = client.post(
        f"{PUB}/{host}/quote", json={**_hold_body(wsite, future(25), nights=1)["quote"], "promo_code": "MONSOON15"}
    )
    assert short.status_code == 422 and short.json()["detail"]["code"] == "promo_invalid"
    assert client.post(f"{PUB}/{host}/quote", json={**body["quote"], "promo_code": "NOPE"}).status_code == 422
    h = client.post(f"{PUB}/{host}/holds", json={**body, "quote": {**body["quote"], "promo_code": "MONSOON15"}}).json()
    assert fake_rzp[-1]["amount_inr"] == 7140.0  # Razorpay asked for the discounted amount
    from tests.test_booking_detail import _connect_razorpay

    _connect_razorpay(db, wsite["tenant"].id, SECRET)
    hold = db.get(BookingHold, h["hold_id"])
    raw, sig = _paid(hold.payment_link_id, "pay_P1", 714000)
    with patch("app.workers.tasks.website.after_booking.delay"):
        client.post(
            f"/api/v1/webhooks/razorpay/{wsite['tenant'].slug}", content=raw, headers={"x-razorpay-signature": sig}
        )
    promo = db.query(WebsitePromoCode).filter_by(tenant_id=wsite["tenant"].id).one()
    db.refresh(promo)
    assert promo.used_count == 1
    assert db.query(AuditEvent).filter_by(tenant_id=wsite["tenant"].id, action="website.promo_used").count() == 1


def test_cap_counts_live_holds_and_flat_never_goes_negative(client, db, wsite, fake_rzp):  # noqa: F811
    host = _v2_live(client, db, wsite)
    _promo(client, wsite, code="ONCE", kind="flat", value=100000, max_uses=1)
    body = _hold_body(wsite, future(40))
    q = client.post(f"{PUB}/{host}/quote", json={**body["quote"], "promo_code": "ONCE"}).json()["quote"]
    assert q["discount"] == "8400" and q["total"] == "0"
    assert (
        client.post(f"{PUB}/{host}/holds", json={**body, "quote": {**body["quote"], "promo_code": "ONCE"}}).status_code
        == 201
    )
    second = _hold_body(wsite, future(50), phone="+919800000011")
    r = client.post(f"{PUB}/{host}/holds", json={**second, "quote": {**second["quote"], "promo_code": "ONCE"}})
    assert r.status_code == 422 and "used up" in r.json()["detail"]["message"]


def test_flat_split_keeps_total():
    rates = [(future(1) + timedelta(days=i), Decimal("1000")) for i in range(3)]
    out = website_pricing._discounted(rates, "flat", Decimal("1000"))
    assert sum(old - new for _, new, old in out) == Decimal("1000") and all(new >= 0 for _, new, _ in out)


def test_handoff_hides_amounts_but_keeps_code(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite, grounded=False)
    _promo(client, wsite)
    q = client.post(
        f"{PUB}/{host}/quote", json={**_hold_body(wsite, future(25))["quote"], "promo_code": "MONSOON15"}
    ).json()
    assert q["quote"]["promo_code"] == "MONSOON15" and "discount" not in q["quote"] and "total" not in q["quote"]
    h = client.post(f"{PUB}/{host}/holds", json=_hold_body(wsite, future(30))).json()
    assert "total" not in h["quote"] and h["payment_url"] is None


def test_offer_band_binds_code_amount_only_when_grounded(client, db, wsite):  # noqa: F811
    _promo(client, wsite, ends_on=future(60).isoformat())
    spec = _spec()
    spec["pages"][0]["sections"].insert(
        1,
        {
            "id": "deal",
            "type": "offer",
            "variant": "banner",
            "slots": {"heading": "Monsoon weekdays", "promo": "MONSOON15"},
        },
    )
    with patch("tests.test_website_v2_booking._spec", return_value=spec):
        host = _v2_live(client, db, wsite, grounded=True)
    promo = client.get(f"{PUB}/{host}/bootstrap").json()["bound"]["deal"]["promo"]
    assert promo["code"] == "MONSOON15" and promo["label"] == "15% off" and promo["until"] == future(60).isoformat()
    wsite["tenant"].brand_config = {**wsite["tenant"].brand_config, "price_disclosure": "handoff"}
    db.commit()
    assert client.get(f"{PUB}/{host}/bootstrap").json()["bound"]["deal"]["promo"]["label"] is None
    bad = _spec()
    bad["pages"][0]["sections"].insert(
        1, {"id": "deal", "type": "offer", "variant": "banner", "slots": {"heading": "15% off now"}}
    )
    assert (
        client.post(f"{BASE}/draft/v2", json={"spec": bad}, headers=wsite["owner_h"]).status_code == 422
    )  # typed discount
