"""Meta ads: adapter parsing and host pinning, idempotent sync, the ad -> lead -> booking -> revenue join,
tenant isolation and the owner/manager guard."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from app.adapters.marketing import meta_ads
from app.core.encryption import encrypt_credentials
from app.core.security import create_access_token, get_password_hash
from app.models.ad_metrics import AdMetric
from app.models.base import gen_uuid
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.models.property import Property, Stay
from app.models.user import User, UserRole
from app.services import meta_ads_service as svc


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _wa_token(db, tenant_id, token="wa-token"):
    db.add(Integration(id=gen_uuid(), tenant_id=tenant_id, kind="whatsapp_meta", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"access_token": token})))
    db.commit()


def _raw(ad="a1", camp="c1", day=None, spend="100.50", conv=4):
    return {"ad_id": ad, "ad_name": f"Ad {ad}", "campaign_id": camp, "campaign_name": f"Camp {camp}",
            "adset_id": "s1", "adset_name": "Set", "date_start": (day or date.today()).isoformat(),
            "spend": spend, "impressions": "2000", "reach": "1500", "clicks": "80", "frequency": "1.3",
            "ctr": "4", "cpm": "50", "account_currency": "INR",
            "actions": [{"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": str(conv)}]}


# ── adapter ──────────────────────────────────────────────────────────────────

def test_parse_row_reads_conversations_and_skips_rows_without_an_ad():
    row = meta_ads.parse_row(_raw(conv=7))
    assert row["conversations_started"] == 7 and row["spend"] == Decimal("100.50") and row["impressions"] == 2000
    assert meta_ads.parse_row({"date_start": "2026-10-01"}) is None
    assert meta_ads.parse_row({"ad_id": "x"}) is None


def test_follows_pagination_but_refuses_a_non_graph_host(monkeypatch):
    page1 = {"data": [_raw("a1")], "paging": {"next": "https://graph.facebook.com/v20.0/next?after=1"}}
    page2 = {"data": [_raw("a2")]}
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        r = MagicMock(); r.status_code = 200
        r.json.return_value = page1 if len(calls) == 1 else page2
        return r
    monkeypatch.setattr(meta_ads.httpx, "get", fake_get)
    rows = list(meta_ads.fetch_insights("t", "123", date.today(), date.today()))
    assert [r["ad_id"] for r in rows] == ["a1", "a2"] and calls[0].endswith("/act_123/insights")

    evil = {"data": [], "paging": {"next": "https://evil.example.com/steal"}}
    monkeypatch.setattr(meta_ads.httpx, "get", lambda *a, **k: MagicMock(status_code=200, json=lambda: evil))
    with pytest.raises(meta_ads.MetaAdsError):
        list(meta_ads.fetch_insights("t", "123", date.today(), date.today()))


def test_error_classification():
    assert meta_ads.MetaAdsError("x", code=17).rate_limited
    assert meta_ads.MetaAdsError("x", status=400, code=190).bad_token
    assert not meta_ads.MetaAdsError("x", status=500).bad_token


# ── sync ─────────────────────────────────────────────────────────────────────

def test_sync_upserts_and_is_idempotent(db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    _wa_token(db, tid)
    svc.select_account(db, tid, "123", "Ratha ads", "INR")
    rows = [meta_ads.parse_row(_raw("a1", spend="100")), meta_ads.parse_row(_raw("a2", spend="50"))]
    monkeypatch.setattr(meta_ads, "fetch_insights", lambda *a, **k: iter(rows))

    first = svc.sync(db, tid)
    assert first["created"] == 2 and db.query(AdMetric).filter_by(tenant_id=tid).count() == 2

    rows[0] = meta_ads.parse_row(_raw("a1", spend="120"))        # Meta restated yesterday's spend
    second = svc.sync(db, tid)
    assert second["created"] == 0 and second["updated"] == 2
    assert db.query(AdMetric).filter_by(tenant_id=tid, ad_id="a1").one().spend == Decimal("120.00")
    assert svc.status(db, tid)["last_synced_at"] and svc.status(db, tid)["last_error"] is None


def test_sync_needs_an_account_and_a_token(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    with pytest.raises(svc.NotConfigured):
        svc.sync(db, tid)
    svc.select_account(db, tid, "123")
    with pytest.raises(svc.NotConfigured):          # account chosen, but no token anywhere
        svc.sync(db, tid)


def test_a_rejected_token_marks_the_integration_errored(db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    _wa_token(db, tid)
    svc.select_account(db, tid, "123")

    def boom(*a, **k):
        raise meta_ads.MetaAdsError("Error validating access token", status=400, code=190)
        yield
    monkeypatch.setattr(meta_ads, "fetch_insights", boom)
    with pytest.raises(meta_ads.MetaAdsError):
        svc.sync(db, tid)
    row = svc.get_row(db, tid)
    assert row.status == "error" and "validating" in row.config["last_error"]


# ── the join ─────────────────────────────────────────────────────────────────

def _lead(db, tid, *, ad_id, campaign_id=None, booked_amount=None, cancelled=False):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush()
    prop = db.query(Property).filter_by(tenant_id=tid).first()
    if prop is None:
        prop = Property(id=gen_uuid(), tenant_id=tid, name="C1", slug=f"c-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
        db.add(prop); db.flush()
    inq = Inquiry(id=gen_uuid(), tenant_id=tid, guest_id=g.id)
    db.add(inq); db.flush()
    conv = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    db.add(LeadAttribution(id=gen_uuid(), tenant_id=tid, inquiry_id=inq.id, conversation_id=conv.id, guest_id=g.id,
                           destination_channel="whatsapp", ad_id=ad_id, campaign_id=campaign_id,
                           first_message_at=datetime.now(timezone.utc)))
    if booked_amount is not None:
        db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, inquiry_id=inq.id,
                    check_in=date.today() + timedelta(days=5), check_out=date.today() + timedelta(days=6),
                    status="cancelled" if cancelled else "confirmed", total_amount=booked_amount))
    db.commit()


def _metric(db, tid, *, ad, camp, spend, conv, day=None):
    db.add(AdMetric(id=gen_uuid(), tenant_id=tid, ad_account_id="act_1", date=day or date.today(),
                    campaign_id=camp, campaign_name=f"Camp {camp}", adset_id="s", ad_id=ad, ad_name=ad,
                    spend=Decimal(spend), impressions=1000, reach=800, clicks=50, conversations_started=conv))
    db.commit()


def test_summary_joins_spend_to_leads_bookings_and_revenue(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _metric(db, tid, ad="a1", camp="c1", spend="10000", conv=20)
    _metric(db, tid, ad="a2", camp="c2", spend="5000", conv=5)
    _lead(db, tid, ad_id="a1", booked_amount=Decimal("40000"))                    # ad resolves to campaign c1
    _lead(db, tid, ad_id=None, campaign_id="c1", booked_amount=Decimal("20000"))
    _lead(db, tid, ad_id="a1", booked_amount=Decimal("99999"), cancelled=True)    # cancelled: no revenue
    _lead(db, tid, ad_id="a2")                                                    # lead, never booked
    _lead(db, tid, ad_id="unknown-ad")                                            # an ad we never synced

    s = svc.summary(db, tid, 30)
    c1 = next(c for c in s["campaigns"] if c["campaign_id"] == "c1")
    assert c1["spend"] == 10000 and c1["meta_conversations"] == 20
    assert c1["haip_leads"] == 3 and c1["bookings"] == 2 and c1["revenue"] == 60000     # 40k + 20k, cancelled excluded
    assert c1["roas"] == 6.0 and c1["cost_per_lead"] == round(10000 / 3, 2)

    c2 = next(c for c in s["campaigns"] if c["campaign_id"] == "c2")
    assert c2["haip_leads"] == 1 and c2["bookings"] == 0 and c2["roas"] == 0.0
    assert any(c["campaign_id"] == svc.UNMATCHED for c in s["campaigns"])           # leads from an unsynced ad stay visible

    t = s["totals"]
    assert t["spend"] == 15000 and t["revenue"] == 60000 and t["roas"] == 4.0
    assert t["meta_conversations"] == 25 and t["haip_conversations"] == 5 and t["attribution_gap"] == 20


def test_summary_is_empty_without_data_and_never_divides_by_zero(db, tenant_and_user):
    s = svc.summary(db, tenant_and_user["tenant"].id, 30)
    assert s["campaigns"] == [] and s["totals"]["roas"] is None and s["totals"]["cost_per_lead"] is None


def test_summary_only_counts_this_workspace(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    other = str(uuid.uuid4())
    _metric(db, other, ad="x1", camp="cx", spend="99999", conv=50)
    _metric(db, tid, ad="a1", camp="c1", spend="100", conv=1)
    s = svc.summary(db, tid, 30)
    assert [c["campaign_id"] for c in s["campaigns"]] == ["c1"] and s["totals"]["spend"] == 100


# ── endpoints ────────────────────────────────────────────────────────────────

def _concierge_token(db, tid, role=UserRole.CONCIERGE):
    u = User(id=gen_uuid(), tenant_id=tid, name="C", email=f"c-{uuid.uuid4().hex[:6]}@t.com", role=role,
             is_active=True, hashed_password=get_password_hash("x" * 12))
    db.add(u); db.commit()
    return create_access_token({"sub": u.id, "tenant_id": tid, "role": u.role.value})


def test_only_owners_and_managers_can_use_it(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    bad = _h(_concierge_token(db, tid))
    for method, path in (("get", "/status"), ("get", "/summary"), ("get", "/accounts"), ("post", "/sync")):
        assert getattr(client, method)(f"/api/v1/marketing/ads{path}", headers=bad).status_code == 403
    assert client.put("/api/v1/marketing/ads/account", json={"ad_account_id": "1234"}, headers=bad).status_code == 403
    assert client.get("/api/v1/marketing/ads/status").status_code in (401, 403)


def test_marketing_role_can_read_but_not_choose_the_account(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(_concierge_token(db, tid, UserRole.MARKETING))
    assert client.get("/api/v1/marketing/ads/status", headers=h).status_code == 200
    assert client.get("/api/v1/marketing/ads/summary", headers=h).status_code == 200
    assert client.get("/api/v1/marketing/ads/accounts", headers=h).status_code == 403
    assert client.put("/api/v1/marketing/ads/account", json={"ad_account_id": "1234"}, headers=h).status_code == 403


def test_choosing_an_account_checks_the_token_can_read_it(client, db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    h = _h(tenant_and_user["access_token"])
    _wa_token(db, tid)
    monkeypatch.setattr(meta_ads, "list_ad_accounts", lambda tok: [{"id": "act_111", "name": "Ratha", "currency": "INR", "status": 1}])

    assert client.put("/api/v1/marketing/ads/account", json={"ad_account_id": "999"}, headers=h).status_code == 422
    assert client.put("/api/v1/marketing/ads/account", json={"ad_account_id": "not-an-id"}, headers=h).status_code == 422

    r = client.put("/api/v1/marketing/ads/account", json={"ad_account_id": "111"}, headers=h)
    assert r.status_code == 200 and r.json()["configured"] and r.json()["ad_account"]["name"] == "Ratha"
    assert client.get("/api/v1/marketing/ads/accounts", headers=h).json()["accounts"][0]["id"] == "act_111"


def test_sync_endpoint_explains_a_rejected_token(client, db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    h = _h(tenant_and_user["access_token"])
    _wa_token(db, tid)
    svc.select_account(db, tid, "111")

    def boom(*a, **k):
        raise meta_ads.MetaAdsError("Invalid OAuth access token", status=400, code=190)
        yield
    monkeypatch.setattr(meta_ads, "fetch_insights", boom)
    r = client.post("/api/v1/marketing/ads/sync", headers=h)
    assert r.status_code == 400 and "Settings" in r.json()["detail"]


def test_summary_endpoint_returns_totals(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _metric(db, tid, ad="a1", camp="c1", spend="2500", conv=5)
    r = client.get("/api/v1/marketing/ads/summary?days=7", headers=_h(tenant_and_user["access_token"]))
    assert r.status_code == 200 and r.json()["totals"]["spend"] == 2500 and r.json()["days"] == 7
    assert client.get("/api/v1/marketing/ads/summary?days=0", headers=_h(tenant_and_user["access_token"])).status_code == 422
