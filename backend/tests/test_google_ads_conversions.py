"""Website growth #5: Google Ads learns from real bookings (Data Manager API uploads, click ids, settings)."""

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.adapters import google_data_manager as gdm
from app.core.encryption import decrypt_credentials
from app.models.base import gen_uuid
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.integration import Integration
from app.models.property import Property, Stay
from app.models.stay_finance import StayAddOn, StayDeposit
from app.models.website import Site, WebsiteEvent
from app.services import google_ads_conversions as gads
from app.services import website_refs
from app.services.date_presets import today_ist
from tests.test_website_v2_booking import _v2_live
from tests.website_fixtures import BASE, make_tenant, wsite  # noqa: F401  (fixture)

PUB = "/api/v1/public/sites"
PHONE, EMAIL = "+919845012345", "Asha.Rao+trips@GoogleMail.com"
GCLID = "EAIaIQobChMI_test-gclid_123"
SETTINGS = {
    "gads_id": "AW-123456789",
    "gads_enquiry_label": "AbC-enq_1",
    "gads_checkout_label": "AbC-chk_2",
    "gads_customer_id": "1234567890",
    "gads_booking_action_id": "987654321",
    "gads_upload_enabled": True,
}


class FakeRedis:
    def __init__(self):
        self.d = {}

    def set(self, k, v, ex=None, nx=False):
        if nx and k in self.d:
            return None
        self.d[k] = v
        return True

    def setex(self, k, ttl, v):
        self.d[k] = v

    def eval(self, _script, _n, k):
        return self.d.pop(k, None)


@pytest.fixture(autouse=True)
def _env():
    r = FakeRedis()
    with (
        patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)),
        patch("app.services.marketing_channel_connections._redis", return_value=r),
        patch.object(gads.settings, "GOOGLE_DATA_MANAGER_CLIENT_ID", "cid"),
        patch.object(gads.settings, "GOOGLE_DATA_MANAGER_CLIENT_SECRET", "csecret"),
        patch.object(gads.settings, "API_BASE_URL", "https://api.example.com"),
    ):
        yield r


def _save(client, w, h="owner_h", **over):
    return client.put(f"{BASE}/tracking", json={**SETTINGS, **over}, headers=w[h])


def _connect(db, tid, *, access="ya29.access", refresh="1//refresh"):
    from app.core.encryption import encrypt_credentials

    integ = Integration(
        tenant_id=tid,
        kind=gads.KIND,
        status="active",
        credentials_kms_blob=encrypt_credentials({"access_token": access, "refresh_token": refresh}),
        config={"expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )
    db.add(integ)
    db.commit()
    return integ


def _booking(
    db,
    tid,
    *,
    consent=True,
    amount="18000",
    addons=("2000",),
    deposit="5000",
    click=None,
    status="confirmed",
    source=InquirySource.WEBSITE,
):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone=PHONE, email=EMAIL)
    db.add(g)
    prop = db.query(Property).filter_by(tenant_id=tid).first()
    inq = Inquiry(
        id=gen_uuid(),
        tenant_id=tid,
        guest_id=g.id,
        source=source,
        custom_fields={"google_click": {"gclid": click}} if click else None,
    )
    db.add(inq)
    if consent is not None:
        db.add(
            Consent(
                tenant_id=tid,
                guest_id=g.id,
                channel="web_form",
                scope="marketing",
                granted=consent,
                recorded_at=datetime.now(UTC).isoformat(),
            )
        )
    today = today_ist()
    s = Stay(
        id=gen_uuid(),
        tenant_id=tid,
        guest_id=g.id,
        property_id=prop.id,
        inquiry_id=inq.id,
        check_in=today + timedelta(days=9),
        check_out=today + timedelta(days=11),
        status=status,
        total_amount=Decimal(amount),
    )
    db.add(s)
    db.flush()
    for a in addons:
        db.add(StayAddOn(tenant_id=tid, stay_id=s.id, name="Bonfire", quantity=1, unit_price=Decimal(a)))
    if deposit:
        db.add(StayDeposit(tenant_id=tid, stay_id=s.id, amount=Decimal(deposit), status="held"))
    db.commit()
    return s


class Post:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, token, body):
        self.calls.append((token, body))
        if self.fail:
            raise self.fail


# ─── settings + connection ────────────────────────────────────────────────────────────────────────────


def test_settings_saved_shown_and_public_labels_only(client, db, wsite):  # noqa: F811
    r = _save(client, wsite)
    assert r.status_code == 200, r.text
    assert r.json()["gads_customer_id"] == "1234567890" and r.json()["gads_upload_enabled"] is True
    got = client.get(f"{BASE}/tracking", headers=wsite["manager_h"]).json()
    assert got["gads_booking_action_id"] == "987654321"
    assert got["google_ads"] == {
        "available": True,
        "connected": False,
        "status": "disconnected",
        "last_error": None,
        "last_upload_at": None,
    }
    from app.services import website_tracking

    pub = website_tracking.public(db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one())
    assert pub["gads"] == {"id": "AW-123456789", "enquiry": "AbC-enq_1", "checkout": "AbC-chk_2"}
    assert "1234567890" not in json.dumps(pub)  # the customer id never reaches the browser


def test_settings_refuse_half_setups_and_wrong_roles(client, wsite):  # noqa: F811
    assert _save(client, wsite, gads_id=None).json()["detail"]["code"] == "gads_id_needed"
    assert _save(client, wsite, gads_booking_action_id=None).json()["detail"]["code"] == "gads_upload_incomplete"
    assert _save(client, wsite, gads_customer_id="123-456-7890").status_code == 422  # digits only (the form strips)
    assert _save(client, wsite, h="foh_h").status_code == 403
    assert _save(client, wsite, h="mkt_h").status_code == 403


def test_settings_are_per_workspace(client, db, wsite):  # noqa: F811
    _save(client, wsite)
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user

    other = make_tenant(db, "Elsewhere")
    _u, h = make_user(db, other.id, UserRole.OWNER)
    assert client.post(f"{BASE}/site", json={}, headers=h).status_code == 201
    got = client.get(f"{BASE}/tracking", headers=h).json()
    assert got["gads_customer_id"] is None and got["gads_upload_enabled"] is False


def test_oauth_start_needs_owner_or_manager(client, db, wsite):  # noqa: F811
    from app.core.security import create_access_token

    tok = create_access_token({"sub": wsite["mkt"].id, "tenant_id": wsite["tenant"].id})
    r = client.get(f"{BASE}/google-ads/oauth-start", params={"token": tok}, follow_redirects=False)
    assert r.status_code == 403
    tok = create_access_token({"sub": wsite["manager"].id, "tenant_id": wsite["tenant"].id})
    r = client.get(f"{BASE}/google-ads/oauth-start", params={"token": tok}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/")
    assert "datamanager" in r.headers["location"] and "access_type=offline" in r.headers["location"]


def test_oauth_finish_stores_tokens_encrypted(db, wsite, _env):  # noqa: F811
    state = gads.start(wsite["tenant"].id, wsite["owner"].id).split("state=")[1].split("&")[0]
    with patch.object(
        gdm, "exchange_code", return_value={"access_token": "ya29.A", "refresh_token": "1//R", "expires_in": 3599}
    ):
        assert gads.finish(db, "code-1", state) == wsite["tenant"].id
    db.commit()
    integ = db.query(Integration).filter_by(tenant_id=wsite["tenant"].id, kind=gads.KIND).one()
    raw = integ.credentials_kms_blob
    raw = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
    assert b"ya29.A" not in raw and b"1//R" not in raw
    assert decrypt_credentials(integ.credentials_kms_blob) == {"access_token": "ya29.A", "refresh_token": "1//R"}
    assert integ.status == "active" and "ya29" not in json.dumps(integ.config)
    from app.services.marketing_content_service import MarketingError

    with pytest.raises(MarketingError):  # single-use state
        gads.finish(db, "code-1", state)


# ─── click ids ────────────────────────────────────────────────────────────────────────────────────────


def test_enquiry_keeps_click_ids_only_with_banner_consent(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    base = {"name": "Ravi Kumar", "gclid": GCLID, "wbraid": "WBRAID_abc12345"}
    client.post(f"{PUB}/{host}/enquiries", json={**base, "phone": "+919812300001"})
    client.post(f"{PUB}/{host}/enquiries", json={**base, "phone": "+919812300002", "analytics_consent": True})
    by_phone = {}
    for inq in db.query(Inquiry).filter_by(tenant_id=wsite["tenant"].id):
        by_phone[db.get(Guest, inq.guest_id).phone] = inq
    assert "google_click" not in (by_phone["+919812300001"].custom_fields or {})
    click = by_phone["+919812300002"].custom_fields["google_click"]
    assert click["gclid"] == GCLID and click["wbraid"] == "WBRAID_abc12345" and click["via"] == "website"
    bad = client.post(f"{PUB}/{host}/enquiries", json={**base, "phone": "+919812300003", "gclid": "<script>"})
    assert bad.status_code == 422


def test_whatsapp_button_code_carries_the_click_to_the_chat_lead(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    assert client.post(f"{PUB}/{host}/wa-click", json={"code": "K7F2Q9XA", "gclid": GCLID}).status_code == 202
    assert client.post(f"{PUB}/{host}/wa-click", json={"code": "bad"}).status_code == 422
    g = Guest(id=gen_uuid(), tenant_id=wsite["tenant"].id, name="Meera", phone="+919812300009")
    db.add(g)
    inq = Inquiry(tenant_id=wsite["tenant"].id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    ref = website_refs.stamp(db, wsite["tenant"].id, inq, "Hi! I'd like to know more. (Ref HV-HOME-BOOK-K7F2Q9XA)")
    assert ref["code"] == "HV-HOME-BOOK"
    assert (
        inq.custom_fields["google_click"]["gclid"] == GCLID and inq.custom_fields["google_click"]["via"] == "whatsapp"
    )
    other = Inquiry(tenant_id=wsite["tenant"].id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(other)
    db.flush()
    website_refs.stamp(db, wsite["tenant"].id, other, "(Ref HV-HOME-BOOK-K7F2Q9XA)")
    assert "google_click" not in (other.custom_fields or {})  # a code is used once


def test_a_click_code_from_another_workspace_is_not_read(client, db, wsite, _env):  # noqa: F811
    other = make_tenant(db, "Elsewhere")
    gads.remember_wa_click(other.id, "K7F2Q9XA", {"gclid": GCLID})
    g = Guest(id=gen_uuid(), tenant_id=wsite["tenant"].id, name="Meera", phone="+919812300011")
    db.add(g)
    inq = Inquiry(tenant_id=wsite["tenant"].id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    assert gads.stamp_from_code(db, wsite["tenant"].id, inq, "K7F2Q9XA") is False


# ─── booking uploads ──────────────────────────────────────────────────────────────────────────────────


def _ready(client, db, wsite):  # noqa: F811
    assert _save(client, wsite).status_code == 200
    return _connect(db, wsite["tenant"].id)


def test_upload_is_hashed_normalised_valued_and_once_per_booking(client, db, wsite, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    _ready(client, db, wsite)
    s = _booking(db, wsite["tenant"].id, click=GCLID)
    post = Post()
    assert gads.send_tenant(db, wsite["tenant"], post=post)["sent"] == 1
    token, body = post.calls[0]
    assert token == "ya29.access"
    dest = body["destinations"][0]
    assert dest == {
        "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": "1234567890"},
        "loginAccount": {"accountType": "GOOGLE_ADS", "accountId": "1234567890"},
        "productDestinationId": "987654321",
    }
    assert body["encoding"] == "HEX" and body["consent"]["adUserData"] == "CONSENT_GRANTED"
    ev = body["events"][0]
    assert ev["transactionId"] == f"stay:{s.id}" and ev["currency"] == "INR" and ev["eventSource"] == "WEB"
    assert ev["conversionValue"] == 20000.0  # 18,000 + 2,000 add-on; the 5,000 deposit is not revenue
    assert ev["adIdentifiers"] == {"gclid": GCLID}
    ids = ev["userData"]["userIdentifiers"]
    assert {"phoneNumber": hashlib.sha256(b"+919845012345").hexdigest()} in ids
    assert {"emailAddress": hashlib.sha256(b"asharao@googlemail.com").hexdigest()} in ids  # Gmail: no dots, no +tag
    dumped = json.dumps(body)
    assert "9845012345" not in dumped and "Asha" not in dumped and "example" not in dumped.lower()
    assert "9845012345" not in caplog.text and "ya29" not in caplog.text and "googlemail" not in caplog.text.lower()
    row = db.query(WebsiteEvent).filter_by(tenant_id=wsite["tenant"].id, event_id=f"gads:stay:{s.id}").one()
    assert row.status == "sent" and row.value == Decimal("20000.00")
    assert gads.send_tenant(db, wsite["tenant"], post=post)["sent"] == 0 and len(post.calls) == 1  # once per booking
    integ = gads.connection(db, wsite["tenant"].id)
    assert integ.config.get("last_upload_at") and not integ.config.get("last_error")


def test_no_marketing_consent_means_nothing_leaves(client, db, wsite):  # noqa: F811
    _ready(client, db, wsite)
    s = _booking(db, wsite["tenant"].id, consent=False, click=GCLID)
    none = _booking(db, wsite["tenant"].id, consent=None)
    post = Post()
    assert gads.send_tenant(db, wsite["tenant"], post=post)["sent"] == 0 and post.calls == []
    for stay in (s, none):
        row = db.query(WebsiteEvent).filter_by(event_id=f"gads:stay:{stay.id}").one()
        assert row.status == "skipped" and row.reason == "no marketing consent"


def test_consent_withdrawn_before_sending_holds_it_back(client, db, wsite):  # noqa: F811
    _ready(client, db, wsite)
    s = _booking(db, wsite["tenant"].id)
    gads.queue_new(db, wsite["tenant"], db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one())
    db.add(
        Consent(
            tenant_id=wsite["tenant"].id,
            guest_id=s.guest_id,
            channel="whatsapp",
            scope="marketing",
            granted=False,
            recorded_at=(datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
        )
    )
    db.commit()
    post = Post()
    gads.send_tenant(db, wsite["tenant"], post=post)
    assert post.calls == []
    assert db.query(WebsiteEvent).filter_by(event_id=f"gads:stay:{s.id}").one().reason == "no marketing consent"


def test_off_until_switched_on_and_connected(client, db, wsite):  # noqa: F811
    _booking(db, wsite["tenant"].id)
    post = Post()
    assert gads.send_tenant(db, wsite["tenant"], post=post) == {"sent": 0, "skipped": "off"}
    _save(client, wsite)
    assert gads.send_tenant(db, wsite["tenant"], post=post) == {"sent": 0, "skipped": "off"}  # not connected
    assert post.calls == [] and db.query(WebsiteEvent).count() == 0


def test_transient_failure_retries_with_backoff(client, db, wsite):  # noqa: F811
    _ready(client, db, wsite)
    s = _booking(db, wsite["tenant"].id)
    post = Post(fail=gdm.DataManagerError("Google answered 503", transient=True))
    assert gads.send_tenant(db, wsite["tenant"], post=post)["failed"] == 1
    row = db.query(WebsiteEvent).filter_by(event_id=f"gads:stay:{s.id}").one()
    assert row.status == "failed" and row.tries == 1 and "503" in row.reason
    gads.send_tenant(db, wsite["tenant"], post=post)
    assert len(post.calls) == 1  # backing off: not retried at once
    later = datetime.now(UTC) + timedelta(minutes=6)
    ok = Post()
    assert gads.send_tenant(db, wsite["tenant"], post=ok, now=later)["sent"] == 1
    assert gads.connection(db, wsite["tenant"].id).config.get("last_error") is None


def test_rejected_login_turns_the_integration_red(client, db, wsite):  # noqa: F811
    _ready(client, db, wsite)
    _booking(db, wsite["tenant"].id)
    post = Post(fail=gdm.DataManagerError("Google refused HAIP's access (401)", transient=False, auth=True))
    gads.send_tenant(db, wsite["tenant"], post=post)
    integ = db.query(Integration).filter_by(tenant_id=wsite["tenant"].id, kind=gads.KIND).one()
    assert integ.status == "error" and "401" in integ.config["last_error"]
    listed = client.get("/api/v1/integrations", headers=wsite["owner_h"]).json()
    card = next(i for i in listed if i["kind"] == gads.KIND)
    assert card["status"] == "error" and "401" in card["config"]["last_error"] and "ya29" not in json.dumps(card)
    assert gads.send_tenant(db, wsite["tenant"], post=Post()) == {"sent": 0, "skipped": "reconnect"}


def test_uploads_stay_inside_the_workspace(client, db, wsite):  # noqa: F811
    _ready(client, db, wsite)
    other = make_tenant(db, "Elsewhere")
    db.add(Property(tenant_id=other.id, name="Far", slug="far", type="villa", is_active=True))
    db.commit()
    theirs = _booking(db, other.id)
    post = Post()
    gads.send_tenant(db, wsite["tenant"], post=post)
    assert all(f"stay:{theirs.id}" not in json.dumps(b) for _t, b in post.calls)
    assert db.query(WebsiteEvent).filter_by(event_id=f"gads:stay:{theirs.id}").count() == 0


def test_cancelled_or_free_bookings_are_not_uploaded(client, db, wsite):  # noqa: F811
    _ready(client, db, wsite)
    c = _booking(db, wsite["tenant"].id, status="cancelled")
    z = _booking(db, wsite["tenant"].id, amount="0", addons=())
    post = Post()
    gads.send_tenant(db, wsite["tenant"], post=post)
    assert post.calls == []
    assert db.query(WebsiteEvent).filter_by(event_id=f"gads:stay:{c.id}").one().reason == "cancelled"
    assert db.query(WebsiteEvent).filter_by(event_id=f"gads:stay:{z.id}").one().reason == "no amount"


def test_email_normalisation_rules():
    assert gads.normalise_email(" J.Doe+x@Gmail.com ") == "jdoe@gmail.com"
    assert gads.normalise_email("J.Doe+x@example.com") == "j.doe+x@example.com"  # other domains keep dots and +
    assert gads.normalise_email("not-an-email") is None
