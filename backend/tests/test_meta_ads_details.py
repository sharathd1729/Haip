"""Meta ads, the fuller picture: every metric, campaign / ad set / ad details, and the month-by-month backfill."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.adapters.marketing import meta_ads
from app.core.encryption import encrypt_credentials
from app.models.ad_entity import AdEntity
from app.models.ad_metrics import AdMetric
from app.models.base import gen_uuid
from app.models.integration import Integration
from app.services import meta_ads_service as svc


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _ready(db, tid):
    db.add(Integration(id=gen_uuid(), tenant_id=tid, kind="whatsapp_meta", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"access_token": "tok"})))
    db.commit()
    svc.select_account(db, tid, "111", "Ratha ads", "INR")


def _raw(**kw):
    base = {"ad_id": "a1", "ad_name": "Ad 1", "campaign_id": "c1", "campaign_name": "Camp", "adset_id": "s1", "adset_name": "Set",
            "date_start": date.today().isoformat(), "spend": "250.00", "impressions": "10000", "reach": "8000", "clicks": "400",
            "unique_clicks": "350", "inline_link_clicks": "120", "frequency": "1.25", "ctr": "4", "cpm": "25", "cpc": "0.625",
            "account_currency": "INR", "actions": [
                {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "30"},
                {"action_type": "onsite_conversion.messaging_first_reply", "value": "22"},
                {"action_type": "post_engagement", "value": "75"}, {"action_type": "video_view", "value": "900"},
                {"action_type": "link_click", "value": "118"}]}
    base.update(kw)
    return base


# ── metrics ──────────────────────────────────────────────────────────────────

def test_every_metric_is_read_and_the_full_action_list_is_kept():
    r = meta_ads.parse_row(_raw())
    assert (r["link_clicks"], r["unique_clicks"], r["post_engagement"], r["video_views"], r["first_replies"]) == (120, 350, 75, 900, 22)
    assert r["cpc"] == Decimal("0.625") and r["conversations_started"] == 30
    assert any(a["action_type"] == "video_view" for a in r["actions"])           # nothing from Meta is thrown away
    assert meta_ads.parse_row(_raw(inline_link_clicks=None))["link_clicks"] == 118   # falls back to the link_click action


# ── details ──────────────────────────────────────────────────────────────────

def test_entities_are_parsed_with_budgets_in_rupees_not_paise():
    camp = meta_ads.parse_entity("campaign", {"id": "c1", "name": "Engagement", "objective": "OUTCOME_ENGAGEMENT",
                                             "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "50000",
                                             "start_time": "2026-09-01T10:00:00+0530"})
    assert camp["daily_budget"] == Decimal("500.00") and camp["objective"] == "OUTCOME_ENGAGEMENT"
    assert camp["starts_at"].year == 2026 and camp["campaign_id"] == "c1"

    ad = meta_ads.parse_entity("ad", {"id": "a1", "name": "Reel", "campaign_id": "c1", "adset_id": "s1", "status": "PAUSED",
                                     "creative": {"title": "Weekend in Coorg", "body": "Book now", "thumbnail_url": "https://x/t.jpg", "id": "z"}})
    assert ad["creative"] == {"title": "Weekend in Coorg", "body": "Book now", "thumbnail_url": "https://x/t.jpg"}
    assert meta_ads.parse_entity("ad", {"name": "no id"}) is None


def test_audience_is_described_in_words():
    s = meta_ads.summarize_targeting({
        "age_min": 25, "age_max": 45, "genders": [2], "publisher_platforms": ["instagram"],
        "geo_locations": {"countries": ["IN"], "cities": [{"name": "Bengaluru"}]},
        "flexible_spec": [{"interests": [{"name": "Camping"}, {"name": "Travel"}]}]})
    assert s["ages"] == "25 to 45" and s["genders"] == ["Women"] and s["places"] == ["IN", "Bengaluru"]
    assert s["interests"] == ["Camping", "Travel"] and s["platforms"] == ["instagram"]
    assert meta_ads.summarize_targeting(None) is None and meta_ads.summarize_targeting({})["genders"] == ["All"]


def test_sync_stores_details_and_keeps_going_when_details_fail(db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    _ready(db, tid)
    monkeypatch.setattr(meta_ads, "fetch_insights", lambda *a, **k: iter([meta_ads.parse_row(_raw())]))
    monkeypatch.setattr(meta_ads, "fetch_entities", lambda *a, **k: iter([
        meta_ads.parse_entity("campaign", {"id": "c1", "name": "Engagement", "status": "ACTIVE", "daily_budget": "50000"})]))
    out = svc.sync(db, tid)
    assert out["entities"] == 1 and db.query(AdEntity).filter_by(tenant_id=tid, level="campaign").one().name == "Engagement"

    def broken(*a, **k):
        raise meta_ads.MetaAdsError("(#100) permission", status=400, code=100)
        yield
    monkeypatch.setattr(meta_ads, "fetch_entities", broken)
    again = svc.sync(db, tid)                                        # numbers still sync
    assert again["entities"] == 0 and svc.status(db, tid)["last_error"] is None


def test_summary_carries_every_metric_the_campaign_details_and_each_ads_creative(db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    _ready(db, tid)
    monkeypatch.setattr(meta_ads, "fetch_insights", lambda *a, **k: iter([meta_ads.parse_row(_raw())]))
    monkeypatch.setattr(meta_ads, "fetch_entities", lambda *a, **k: iter([
        meta_ads.parse_entity("campaign", {"id": "c1", "name": "Engagement", "objective": "OUTCOME_ENGAGEMENT", "status": "ACTIVE", "daily_budget": "50000"}),
        meta_ads.parse_entity("adset", {"id": "s1", "name": "Women 25-45", "targeting": {"age_min": 25, "age_max": 45, "genders": [2]}}),
        meta_ads.parse_entity("ad", {"id": "a1", "name": "Reel 1", "campaign_id": "c1", "adset_id": "s1",
                                    "creative": {"title": "Weekend in Coorg", "thumbnail_url": "https://x/t.jpg"}})]))
    svc.sync(db, tid)

    s = svc.summary(db, tid, 30)
    c = s["campaigns"][0]
    assert c["campaign_name"] == "Engagement" and c["objective"] == "OUTCOME_ENGAGEMENT" and c["daily_budget"] == 500.0
    assert (c["impressions"], c["clicks"], c["link_clicks"], c["post_engagement"], c["video_views"], c["first_replies"]) == (10000, 400, 120, 75, 900, 22)
    assert c["ctr"] == 4.0 and c["cpm"] == 25.0 and c["cpc"] == 0.62 and c["cost_per_conversation"] == round(250 / 30, 2)
    ad = c["ad_details"][0]
    assert ad["name"] == "Reel 1" and ad["creative"]["title"] == "Weekend in Coorg" and ad["adset_name"] == "Women 25-45"
    assert ad["audience"]["ages"] == "25 to 45"
    t = s["totals"]
    assert t["impressions"] == 10000 and t["link_clicks"] == 120 and t["ctr"] == 4.0 and t["cpm"] == 25.0
    assert s["daily"][0]["impressions"] == 10000 and s["daily"][0]["clicks"] == 400


def test_workspaces_do_not_see_each_others_details(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    db.add(AdEntity(id=gen_uuid(), tenant_id=str(uuid.uuid4()), ad_account_id="act_9", level="campaign", entity_id="c1", name="Other tenant"))
    db.add(AdMetric(id=gen_uuid(), tenant_id=tid, ad_account_id="act_1", date=date.today(), campaign_id="c1", campaign_name="Mine",
                    adset_id="s", ad_id="a1", ad_name="A", spend=Decimal("10")))
    db.commit()
    assert svc.summary(db, tid, 30)["campaigns"][0]["campaign_name"] == "Mine"


# ── backfill ─────────────────────────────────────────────────────────────────

def test_backfill_plan_is_month_sized_newest_first_and_capped():
    plan = svc.backfill_plan(3)
    assert plan[0][1] == date.today() and len(plan) == 3
    assert all((hi - lo).days <= 29 for lo, hi in plan)
    assert plan[1][1] == plan[0][0] - timedelta(days=1)                      # contiguous, no gaps or overlaps
    assert len(svc.backfill_plan(500)) == len(svc.backfill_plan(svc.MAX_BACKFILL_MONTHS))


def test_backfill_loads_every_window_and_records_progress(db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    _ready(db, tid)
    seen = []

    def fake(token, acct, lo, hi, **k):
        seen.append((lo, hi))
        yield meta_ads.parse_row(_raw(ad_id=f"ad-{hi.isoformat()}", date_start=hi.isoformat()))
    monkeypatch.setattr(meta_ads, "fetch_insights", fake)
    monkeypatch.setattr(meta_ads, "fetch_entities", lambda *a, **k: iter([]))

    state = svc.backfill(db, tid, months=3)
    assert state["state"] == "done" and state["done"] == state["total"] == 3 and state["rows"] == 3 and state["failed"] == []
    assert db.query(AdMetric).filter_by(tenant_id=tid).count() == 3
    assert svc.status(db, tid)["backfill"]["state"] == "done" and svc.status(db, tid)["earliest_data"]

    svc.backfill(db, tid, months=3)                                          # running it again changes nothing
    assert db.query(AdMetric).filter_by(tenant_id=tid).count() == 3


def test_backfill_skips_a_window_meta_refuses_but_stops_on_a_rate_limit(db, tenant_and_user, monkeypatch):
    tid = tenant_and_user["tenant"].id
    _ready(db, tid)
    monkeypatch.setattr(meta_ads, "fetch_entities", lambda *a, **k: iter([]))
    calls = {"n": 0}

    def refuse_second(token, acct, lo, hi, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise meta_ads.MetaAdsError("Please reduce the amount of data", status=400, code=1)
        yield meta_ads.parse_row(_raw(ad_id=f"ad-{calls['n']}", date_start=hi.isoformat()))
    monkeypatch.setattr(meta_ads, "fetch_insights", refuse_second)
    state = svc.backfill(db, tid, months=3)
    assert state["state"] == "done" and len(state["failed"]) == 1 and state["rows"] == 2

    calls["n"] = 0

    def limited(token, acct, lo, hi, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise meta_ads.MetaAdsError("Too many calls", status=400, code=17)
        yield meta_ads.parse_row(_raw(ad_id=f"lim-{calls['n']}", date_start=hi.isoformat()))
    monkeypatch.setattr(meta_ads, "fetch_insights", limited)
    state = svc.backfill(db, tid, months=3)
    assert state["state"] == "stopped" and state["stopped_because"] == "rate_limited" and state["done"] == 1


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_backfill_endpoint_queues_once_and_is_owner_manager_only(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(tenant_and_user["access_token"])
    assert client.post("/api/v1/marketing/ads/backfill", json={"months": 12}, headers=h).status_code == 400    # no account yet
    _ready(db, tid)

    with patch("app.services.meta_ads_service.queue_backfill") as queued:
        r = client.post("/api/v1/marketing/ads/backfill", json={"months": 6}, headers=h)
        assert r.status_code == 202 and r.json()["backfill"]["state"] == "queued" and r.json()["backfill"]["total"] == 6
        assert queued.call_args.args == (tid, 6)

        assert client.post("/api/v1/marketing/ads/backfill", json={"months": 6}, headers=h).status_code == 409   # already running
        assert queued.call_count == 1

    assert client.post("/api/v1/marketing/ads/backfill", json={"months": 99}, headers=h).status_code == 422


def test_backfill_endpoint_refuses_other_roles(client, db, tenant_and_user):
    from app.core.security import create_access_token, get_password_hash
    from app.models.user import User, UserRole
    tid = tenant_and_user["tenant"].id
    u = User(id=gen_uuid(), tenant_id=tid, name="M", email=f"m-{uuid.uuid4().hex[:6]}@t.com", role=UserRole.MARKETING,
             is_active=True, hashed_password=get_password_hash("x" * 12))
    db.add(u); db.commit()
    tok = create_access_token({"sub": u.id, "tenant_id": tid, "role": u.role.value})
    assert client.post("/api/v1/marketing/ads/backfill", json={"months": 3}, headers=_h(tok)).status_code == 403


def test_summary_accepts_up_to_three_years(client, tenant_and_user):
    h = _h(tenant_and_user["access_token"])
    assert client.get("/api/v1/marketing/ads/summary?days=1095", headers=h).status_code == 200
    assert client.get("/api/v1/marketing/ads/summary?days=1200", headers=h).status_code == 422
