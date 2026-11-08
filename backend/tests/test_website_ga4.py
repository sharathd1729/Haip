"""GA4 server purchase (Measurement Protocol) + AI-assistant referrers in the website report."""

import logging
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest

from app.models.user import UserRole
from app.models.website import BookingHold, Site, WebsiteEvent
from app.services import website_report, website_tracking
from tests.test_marketing_studio_content import make_user
from tests.test_website_booking import fake_rzp  # noqa: F401  (fixture)
from tests.test_website_v2_booking import SECRET, _hold_body, _paid, _v2_live
from tests.website_fixtures import BASE, future, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"
GA4 = "G-ABC1234"
MP_SECRET = "mpSecretXYZ987"
CID = "1234567890.1699999999"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


class Post:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, measurement_id, secret, body):
        self.calls.append((measurement_id, secret, body))
        if self.fail:
            raise self.fail


def _ga4_on(client, w, h="owner_h"):
    r = client.put(f"{BASE}/tracking", json={"ga4_id": GA4, "ga4_api_secret": MP_SECRET}, headers=w[h])
    assert r.status_code == 200, r.text
    return r.json()


def _book(client, db, w, *, consent: bool, cid: str | None = CID):
    from tests.test_booking_detail import _connect_razorpay

    host = _v2_live(client, db, w)
    body = {**_hold_body(w, future(30)), "analytics_consent": consent}
    if cid:
        body["ga_client_id"] = cid
    out = client.post(f"{PUB}/{host}/holds", json=body).json()
    _connect_razorpay(db, w["tenant"].id, SECRET)
    hold = db.get(BookingHold, out["hold_id"])
    raw, sig = _paid(hold.payment_link_id, "pay_G1", int(float(hold.pay_now) * 100))
    with patch("app.workers.tasks.website.after_booking.delay"):
        client.post(f"/api/v1/webhooks/razorpay/{w['tenant'].slug}", content=raw, headers={"x-razorpay-signature": sig})
    db.refresh(hold)
    return host, out, hold


def test_settings_encrypt_secret_and_never_return_it(client, db, wsite, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    out = _ga4_on(client, wsite)
    assert out["has_ga4_api_secret"] and out["ga4_server"] and MP_SECRET not in str(out)
    site = db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one()
    db.refresh(site)
    assert MP_SECRET not in (site.ga4_secret_enc or "") and website_tracking._ga4_secret(site) == MP_SECRET
    got = client.get(f"{BASE}/tracking", headers=wsite["manager_h"]).json()
    assert got["has_ga4_api_secret"] and MP_SECRET not in str(got)
    # None keeps it, "" removes it
    client.put(f"{BASE}/tracking", json={"ga4_id": GA4}, headers=wsite["owner_h"])
    db.refresh(site)
    assert website_tracking._ga4_secret(site) == MP_SECRET
    client.put(f"{BASE}/tracking", json={"ga4_id": GA4, "ga4_api_secret": ""}, headers=wsite["owner_h"])
    db.refresh(site)
    assert site.ga4_secret_enc is None
    assert MP_SECRET not in caplog.text


def test_settings_roles_and_validation(client, db, wsite):  # noqa: F811
    body = {"ga4_id": GA4, "ga4_api_secret": MP_SECRET}
    assert client.put(f"{BASE}/tracking", json=body, headers=wsite["mkt_h"]).status_code == 403
    r = client.put(f"{BASE}/tracking", json={"ga4_api_secret": MP_SECRET}, headers=wsite["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ga4_needed"


def test_settings_are_per_workspace(client, db, wsite):  # noqa: F811
    _ga4_on(client, wsite)
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/tracking", headers=other_h).status_code == 404
    assert client.put(f"{BASE}/tracking", json={"ga4_id": GA4}, headers=other_h).status_code == 404


def test_paid_booking_sends_one_purchase_with_the_browser_transaction_id(client, db, wsite, fake_rzp, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    _ga4_on(client, wsite)
    host, out, hold = _book(client, db, wsite, consent=True)
    assert hold.analytics_consent is True and hold.ga_client_id == CID
    st = client.get(f"{PUB}/{host}/holds/{hold.id}", params={"s": out["session"]}).json()
    row = db.query(WebsiteEvent).filter_by(event_id=f"ga4:stay:{hold.stay_id}").one()
    assert row.status == "pending" and row.ga_client_id == CID and float(row.value) == float(hold.total)
    post = Post()
    assert website_tracking.send_ga4_tenant(db, wsite["tenant"], post=post)["sent"] == 1
    mid, secret, body = post.calls[0]
    assert (mid, secret) == (GA4, MP_SECRET) and body["client_id"] == CID
    ev = body["events"][0]
    assert ev["name"] == "purchase" and ev["params"]["transaction_id"] == st["event_id"] == f"stay:{hold.stay_id}"
    assert ev["params"]["currency"] == "INR" and ev["params"]["value"] == float(hold.total)
    db.refresh(row)
    assert row.status == "sent"
    # idempotent: a second queue attempt for the same stay and a second beat run send nothing more
    website_tracking.ga4_purchase(db, db.get(Site, hold.site_id), hold, type("S", (), {"id": hold.stay_id}))
    assert db.query(WebsiteEvent).filter(WebsiteEvent.event_id.startswith("ga4:")).count() == 1
    assert website_tracking.send_ga4_tenant(db, wsite["tenant"], post=post)["sent"] == 0
    assert len(post.calls) == 1
    assert MP_SECRET not in caplog.text


def test_no_purchase_without_analytics_consent(client, db, wsite, fake_rzp):  # noqa: F811
    _ga4_on(client, wsite)
    _host, _out, hold = _book(client, db, wsite, consent=False)
    assert hold.ga_client_id is None  # the browser id is not even kept
    row = db.query(WebsiteEvent).filter_by(event_id=f"ga4:stay:{hold.stay_id}").one()
    assert row.status == "skipped" and row.reason == "no analytics consent" and row.ga_client_id is None
    post = Post()
    assert website_tracking.send_ga4_tenant(db, wsite["tenant"], post=post)["sent"] == 0 and not post.calls


def test_consent_without_ga_cookie_gets_a_server_client_id(client, db, wsite, fake_rzp):  # noqa: F811
    _ga4_on(client, wsite)
    _host, _out, hold = _book(client, db, wsite, consent=True, cid=None)
    row = db.query(WebsiteEvent).filter_by(event_id=f"ga4:stay:{hold.stay_id}").one()
    assert row.status == "pending" and row.ga_client_id and "." in row.ga_client_id


def test_failure_backs_off_and_never_logs_the_secret(client, db, wsite, fake_rzp, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    _ga4_on(client, wsite)
    _host, _out, hold = _book(client, db, wsite, consent=True)
    url = f"{website_tracking.GA4_URL}?measurement_id={GA4}&api_secret={MP_SECRET}"
    post = Post(fail=httpx.ConnectError(f"boom {url}"))
    out = website_tracking.send_ga4_tenant(db, wsite["tenant"], post=post)
    assert out == {"sent": 0, "failed": 1}
    row = db.query(WebsiteEvent).filter_by(event_id=f"ga4:stay:{hold.stay_id}").one()
    assert row.status == "failed" and row.tries == 1 and MP_SECRET not in (row.reason or "")
    # inside the back-off window: not retried yet
    assert website_tracking.send_ga4_tenant(db, wsite["tenant"], post=Post())["sent"] == 0
    row.updated_at = row.updated_at - timedelta(minutes=6)
    db.flush()
    assert website_tracking.send_ga4_tenant(db, wsite["tenant"], post=Post())["sent"] == 1
    got = client.get(f"{BASE}/tracking", headers=wsite["owner_h"]).json()
    assert MP_SECRET not in str(got) and MP_SECRET not in caplog.text


def test_meta_sender_ignores_ga4_rows(client, db, wsite, fake_rzp):  # noqa: F811
    from tests.test_website_tracking import FakeWriter

    client.put(
        f"{BASE}/tracking",
        json={
            "pixel_id": "123456789012345",
            "capi_enabled": True,
            "capi_token": "EAAx",
            "ga4_id": GA4,
            "ga4_api_secret": MP_SECRET,
        },
        headers=wsite["owner_h"],
    )
    _book(client, db, wsite, consent=True)
    FakeWriter.calls = []
    website_tracking.send_tenant(db, wsite["tenant"], writer_factory=FakeWriter)
    names = [e["event_name"] for c in FakeWriter.calls for e in c["events"]]
    assert "purchase" not in names


def test_other_workspace_rows_are_not_sent(client, db, wsite, fake_rzp):  # noqa: F811
    _ga4_on(client, wsite)
    _book(client, db, wsite, consent=True)
    other = make_tenant(db, "Elsewhere")
    assert website_tracking.send_ga4_tenant(db, other, post=Post()) == {"sent": 0, "skipped": "off"}


@pytest.mark.parametrize(
    "src",
    [
        "chatgpt.com",
        "chat.openai.com",
        "www.perplexity.ai",
        "perplexity.ai",
        "gemini.google.com",
        "copilot.microsoft.com",
        "claude.ai",
        "ChatGPT",
        "https://chatgpt.com/c/abc",
    ],
)
def test_ai_referrers_are_one_source(src):
    assert website_report.norm(src) == website_report.AI_ASSISTANTS


@pytest.mark.parametrize(
    "src,expected",
    [
        ("www.google.com", "google"),
        ("l.instagram.com", "instagram"),
        ("Instagram", "instagram"),
        ("", "direct"),
        ("notclaude.ai.example.com", "notclaude"),
        ("google.com", "google"),
    ],
)
def test_other_sources_unchanged(src, expected):
    assert website_report.norm(src) == expected
