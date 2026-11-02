"""Website phase 2 (measurement): tracking settings, server-side Conversions API events with the browser's event_id,
consent gating, WhatsApp button refs on the chat's lead, and the visits -> enquiries -> bookings report.
Nothing reaches Meta: the writer is a fake."""
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry, InquirySource
from app.models.user import UserRole
from app.models.website import Site, WebsiteEvent
from app.services import website_refs, website_report, website_tracking
from tests.test_marketing_studio_content import make_user
from tests.test_website_booking import fake_rzp  # noqa: F401  (fixture)
from tests.test_website_v2_booking import SECRET, _hold_body, _paid, _v2_live
from tests.website_fixtures import BASE, future, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"
PIXEL = "123456789012345"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


class FakeWriter:
    calls: list = []

    def __init__(self, token):
        self.token = token

    def send_events(self, dataset_id, events, *, test_code=None):
        FakeWriter.calls.append({"token": self.token, "dataset": dataset_id, "events": events, "test": test_code})
        return {"events_received": len(events), "fbtrace_id": "t"}

    def close(self):
        pass


def _track_on(client, w, **kw):
    body = {"pixel_id": PIXEL, "ga4_id": "G-ABC1234", "capi_enabled": True, "capi_token": "EAAsecret", **kw}
    r = client.put(f"{BASE}/tracking", json=body, headers=w["owner_h"])
    assert r.status_code == 200, r.text
    return r.json()


def test_tracking_settings_encrypt_token_and_roles(client, db, wsite):  # noqa: F811
    out = _track_on(client, wsite)
    assert out["has_capi_token"] and "capi_token" not in out and out["pixel_id"] == PIXEL
    site = db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one()
    db.refresh(site)
    assert "EAAsecret" not in (site.capi_token_enc or "") and website_tracking._token(site) == "EAAsecret"
    got = client.get(f"{BASE}/tracking", headers=wsite["manager_h"]).json()
    assert got["has_capi_token"] and "EAAsecret" not in str(got)
    # keep the token when it is not sent again
    client.put(f"{BASE}/tracking", json={"pixel_id": PIXEL, "capi_enabled": True}, headers=wsite["owner_h"])
    db.refresh(site)
    assert website_tracking._token(site) == "EAAsecret"
    assert db.query(AuditEvent).filter_by(tenant_id=wsite["tenant"].id, action="website.tracking_changed").count() == 2
    # marketing may read the website but not change what guests' browsers load
    assert client.put(f"{BASE}/tracking", json={"pixel_id": PIXEL}, headers=wsite["mkt_h"]).status_code == 403
    bad = client.put(f"{BASE}/tracking", json={"pixel_id": "not-a-pixel"}, headers=wsite["owner_h"])
    assert bad.status_code == 422
    assert client.put(f"{BASE}/tracking", json={"capi_enabled": True}, headers=wsite["owner_h"]).status_code == 422


def test_tracking_is_per_workspace(client, db, wsite):  # noqa: F811
    _track_on(client, wsite)
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    r = client.get(f"{BASE}/tracking", headers=other_h)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_site"    # never this workspace's settings
    assert client.get(f"{BASE}/report", headers=other_h).status_code == 404


def test_bootstrap_carries_only_public_ids(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    _track_on(client, wsite)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert boot["tracking"] == {"pixel_id": PIXEL, "ga4_id": "G-ABC1234"}
    assert "EAA" not in str(boot)


def test_enquiry_lead_event_needs_marketing_consent(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    _track_on(client, wsite)
    base = {"name": "Ravi Kumar", "phone": "+919812300001", "path": "/stays", "fbp": "fb.1.1.2"}
    no = client.post(f"{PUB}/{host}/enquiries", json=base).json()
    yes = client.post(f"{PUB}/{host}/enquiries", json={**base, "phone": "+919812300002",
                                                       "consent": {"marketing": True}}).json()
    assert no["event_id"].startswith("wl:") and yes["event_id"].startswith("wl:")
    rows = {r.event_id: r for r in db.query(WebsiteEvent).filter_by(tenant_id=wsite["tenant"].id)}
    assert rows[no["event_id"]].status == "skipped" and rows[no["event_id"]].reason == "no marketing consent"
    assert rows[yes["event_id"]].status == "pending" and rows[yes["event_id"]].source_url == f"https://{host}/stays"
    FakeWriter.calls = []
    out = website_tracking.send_tenant(db, wsite["tenant"], writer_factory=FakeWriter)
    assert out["sent"] == 1
    ev = FakeWriter.calls[0]["events"][0]
    assert FakeWriter.calls[0]["dataset"] == PIXEL and FakeWriter.calls[0]["token"] == "EAAsecret"
    assert ev["event_id"] == yes["event_id"] and ev["action_source"] == "website" and ev["user_data"]["fbp"] == "fb.1.1.2"
    assert "+919812300002" not in str(ev) and len(ev["user_data"]["ph"][0]) == 64      # hashed only
    assert db.query(WebsiteEvent).filter_by(event_id=yes["event_id"]).one().status == "sent"


def test_paid_booking_sends_checkout_then_purchase_with_the_stay_id(client, db, wsite, fake_rzp):  # noqa: F811
    from tests.test_booking_detail import _connect_razorpay
    from app.models.website import BookingHold
    host = _v2_live(client, db, wsite)
    _track_on(client, wsite)
    body = {**_hold_body(wsite, future(30)), "consent": {"transactional": True, "marketing": True}, "fbc": "fb.1.1.abc"}
    out = client.post(f"{PUB}/{host}/holds", json=body).json()
    assert out["event_id"] == f"wc:{out['hold_id']}"
    _connect_razorpay(db, wsite["tenant"].id, SECRET)
    hold = db.get(BookingHold, out["hold_id"])
    raw, sig = _paid(hold.payment_link_id, "pay_T1", int(float(hold.pay_now) * 100))
    with patch("app.workers.tasks.website.after_booking.delay"):
        client.post(f"/api/v1/webhooks/razorpay/{wsite['tenant'].slug}", content=raw, headers={"x-razorpay-signature": sig})
    db.refresh(hold)
    st = client.get(f"{PUB}/{host}/holds/{hold.id}", params={"s": out["session"]}).json()
    assert st["event_id"] == f"stay:{hold.stay_id}"          # what the browser's Purchase uses
    purchase = db.query(WebsiteEvent).filter_by(event_id=f"stay:{hold.stay_id}").one()
    assert purchase.event_name == "Purchase" and purchase.fbc == "fb.1.1.abc" and purchase.status == "pending"


def test_no_rows_when_capi_is_off(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    r = client.post(f"{PUB}/{host}/enquiries", json={"name": "Ravi", "phone": "+919812300003",
                                                       "consent": {"marketing": True}})
    assert r.json()["event_id"].startswith("wl:")       # the browser pixel still gets an id
    assert db.query(WebsiteEvent).count() == 0


def test_whatsapp_ref_stamps_the_lead(client, db, wsite):  # noqa: F811
    _v2_live(client, db, wsite)
    prefix = website_refs.site_prefix(db, wsite["tenant"].id)
    assert prefix == "HV"                                   # "Hill Villas"
    from app.services import identity_service
    gid, _ = identity_service.resolve_gid(db, wsite["tenant"].id, signal_type="phone", value="+919812300009",
                                          source="whatsapp", guest_fields={"name": "Meera"})
    inq = Inquiry(tenant_id=wsite["tenant"].id, guest_id=gid, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    assert website_refs.stamp(db, wsite["tenant"].id, inq, "Hi! (Ref ZZ-HOME-HERO)") is None   # not this site's code
    ref = website_refs.stamp(db, wsite["tenant"].id, inq, "Hi! I'd like to know more. (Ref HV-HOME-BOOK)")
    assert ref == {"code": "HV-HOME-BOOK", "page": "HOME", "section": "BOOK"}
    assert inq.source == InquirySource.WEBSITE and inq.custom_fields["website_ref"]["code"] == "HV-HOME-BOOK"
    assert website_refs.stamp(db, wsite["tenant"].id, inq, "(Ref HV-HOME-HERO)") is None       # written once
    db.commit()
    rep = client.get(f"{BASE}/report", headers=wsite["mkt_h"]).json()
    assert rep["buttons"][0] == {"code": "HV-HOME-BOOK", "enquiries": 1, "bookings": 0}
    assert any(r["source"] == "whatsapp button" and r["enquiries"] == 1 for r in rep["rows"])


def test_report_joins_visits_and_enquiries_by_source(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    for src in ("l.instagram.com", "instagram", "google.co.in"):
        client.post(f"{PUB}/{host}/views", json={"path": "/", "source": src})
    client.post(f"{PUB}/{host}/enquiries", json={"name": "Asha", "phone": "+919812300010",
                                                  "utm": {"utm_source": "Instagram"}})
    rep = client.get(f"{BASE}/report", headers=wsite["owner_h"]).json()
    ig = next(r for r in rep["rows"] if r["source"] == "instagram")
    assert ig["visits"] == 2 and ig["enquiries"] == 1 and ig["enquiry_rate"] == 0.5 and "value" in ig
    assert next(r for r in rep["rows"] if r["source"] == "google")["visits"] == 1
    assert website_report.norm("www.google.com") == "google" and website_report.norm("") == "direct"
