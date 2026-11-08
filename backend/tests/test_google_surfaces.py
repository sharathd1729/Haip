"""Google surfaces: Business Profile performance, Search Console, PageSpeed Insights.

Every Google answer here is a fixture through httpx.MockTransport (nothing leaves the machine). Covers: each pull parses its
fixture into rows; a re-run gives the same rows; a quota answer backs off and turns the connection amber on the
Integrations health; disconnect deletes the API data; the shared metrics say None ("No data") on empty and never compare
against an empty period; tokens stay encrypted and out of logs; the endpoints' roles and tenant isolation.
"""

import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from structlog.testing import capture_logs

from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.google_surfaces import GbpDailyMetric, GscDailyTotal, GscSearchRow, PageSpeedRun
from app.models.integration import Integration
from app.services import google_metrics, integration_health
from app.services import google_surfaces_sync as sync
from app.services import marketing_channel_connections as conns
from app.services import search_console_connection as gsc
from app.services.marketing_content_service import MarketingError
from tests.test_marketing_channels import FakeRedis, _env  # noqa: F401  (fixture)
from tests.website_fixtures import BASE, host_of, make_tenant, publish_live, wsite  # noqa: F401

TODAY = date(2026, 11, 8)
GOOG = f"{BASE}/google"


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _connect_gbp(db, tid, locations=("locations/9",)):
    db.add(
        Integration(
            tenant_id=tid,
            kind="google_business",
            status="active",
            credentials_kms_blob=encrypt_credentials({"access_token": "ga-secret", "refresh_token": "gr-secret"}),
            config={
                "account": "accounts/1",
                "location": locations[0],
                "title": "Green Goose",
                "locations": [{"account": "accounts/1", "location": loc, "title": loc} for loc in locations],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
    )
    db.commit()


def _connect_gsc(db, tid, prop="sc-domain:example.com", permission="siteOwner"):
    db.add(
        Integration(
            tenant_id=tid,
            kind="search_console",
            status="active",
            credentials_kms_blob=encrypt_credentials({"access_token": "sa-secret", "refresh_token": "sr-secret"}),
            config={
                "property": prop,
                "properties": [{"site_url": prop, "permission": permission}],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
    )
    db.commit()


def _perf_fixture(req):
    d = lambda y, m, dd: {"year": y, "month": m, "day": dd}  # noqa: E731
    return httpx.Response(
        200,
        json={
            "multiDailyMetricTimeSeries": [
                {
                    "dailyMetricTimeSeries": [
                        {
                            "dailyMetric": "WEBSITE_CLICKS",
                            "timeSeries": {
                                "datedValues": [{"date": d(2026, 11, 1), "value": "7"}, {"date": d(2026, 11, 2)}]
                            },
                        },  # no value = 0
                        {
                            "dailyMetric": "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
                            "timeSeries": {"datedValues": [{"date": d(2026, 11, 1), "value": "120"}]},
                        },
                        {
                            "dailyMetric": "BUSINESS_FOOD_ORDERS",
                            "timeSeries": {"datedValues": [{"date": d(2026, 11, 1), "value": "3"}]},
                        },
                    ]
                }
            ]
        },
    )


# ── Business Profile Performance ─────────────────────────────────────────────────────────────────────────────────────


def test_gbp_pull_parses_rows_backfills_once_and_rerun_is_idempotent(db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    _connect_gbp(db, tid)
    starts = []

    def handler(req):
        assert req.url.host == "businessprofileperformance.googleapis.com"
        q = parse_qs(urlparse(str(req.url)).query)
        starts.append(
            date(
                int(q["dailyRange.startDate.year"][0]),
                int(q["dailyRange.startDate.month"][0]),
                int(q["dailyRange.startDate.day"][0]),
            )
        )
        assert "WEBSITE_CLICKS" in q["dailyMetrics"]
        return _perf_fixture(req)

    out = sync.pull_gbp(db, tid, TODAY, http=_mock(handler))
    db.commit()
    assert out["stored"] > 0 and min(starts) == TODAY - timedelta(days=sync.GBP_BACKFILL_DAYS)  # 18-month backfill
    rows = {(r.day, r.metric): r.value for r in db.query(GbpDailyMetric).filter_by(tenant_id=tid)}
    assert rows == {
        (date(2026, 11, 1), "WEBSITE_CLICKS"): 7,
        (date(2026, 11, 2), "WEBSITE_CLICKS"): 0,
        (date(2026, 11, 1), "BUSINESS_IMPRESSIONS_MOBILE_SEARCH"): 120,
    }  # food orders dropped
    starts.clear()
    sync.pull_gbp(db, tid, TODAY, http=_mock(handler))
    db.commit()
    assert starts == [TODAY - timedelta(days=sync.GBP_RECENT_DAYS)]  # daily: recent only
    assert db.query(GbpDailyMetric).filter_by(tenant_id=tid).count() == 3


def test_gbp_quota_backs_off_and_shows_on_integration_health(db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    _connect_gbp(db, tid)
    out = sync.pull_gbp(db, tid, TODAY, http=_mock(lambda r: httpx.Response(429, json={"error": {"code": 429}})))
    db.commit()
    assert out["failed"] and out["status"] == 429
    integ = conns.connection(db, tid, "google_business")
    st = integ.config["metrics_pull"]
    assert st["failures"] == 1 and "limit" in st["last_error"]
    assert datetime.fromisoformat(st["backoff_until"]) > datetime.now(UTC)
    assert integration_health.classify(integ.kind, integ.status, None, config=integ.config) == integration_health.YELLOW
    with pytest.raises(sync.Skipped):
        sync.pull_gbp(db, tid, TODAY)  # backing off: Google is not asked again
    for _ in range(2):
        sync.record_failure(integ, sync.PublishError("x", transient=True, status=503))
    assert integration_health.classify(integ.kind, integ.status, None, config=integ.config) == integration_health.RED


def test_dashboard_health_names_the_failing_google_pull(client, db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    _connect_gbp(db, tid)
    sync.pull_gbp(db, tid, TODAY, http=_mock(lambda r: httpx.Response(429, json={})))
    db.commit()
    r = client.get("/api/v1/health/dashboard", headers=wsite["owner_h"])
    row = next(s for s in r.json()["services"] if s["name"] == "google_business")
    assert row["status"] == "yellow" and "limit" in row["message"]


# ── Search Console ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_property_matching_domain_vs_url_prefix():
    props = [
        {"site_url": "sc-domain:example.com", "permission": "siteOwner"},
        {"site_url": "https://www.example.com/", "permission": "siteFullUser"},
        {"site_url": "https://other.in/", "permission": "siteUnverifiedUser"},
    ]
    assert gsc.match_property(props, "www.example.com", ["www.example.com"]) == "https://www.example.com/"
    assert gsc.match_property(props, "stay.example.com", ["stay.example.com"]) == "sc-domain:example.com"
    assert gsc.match_property(props, "other.in", ["other.in"]) is None  # unverified never counts
    assert gsc.match_property(props, "a.sites.x", ["a.sites.x", "www.example.com"]) == "https://www.example.com/"
    assert gsc.covers("sc-domain:example.com", "example.com") and not gsc.covers(
        "sc-domain:example.com", "badexample.com"
    )


def test_search_console_login_stores_tokens_encrypted_and_never_returns_them(db, wsite, monkeypatch, _env):  # noqa: F811
    tid = wsite["tenant"].id
    r = FakeRedis()
    monkeypatch.setattr(conns, "_redis", lambda: r)
    host = host_of(wsite)
    puts = []

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "at-secret", "refresh_token": "rt-secret", "expires_in": 3600}
            )
        if req.method == "PUT":
            puts.append(str(req.url))
            return httpx.Response(204)
        return httpx.Response(
            200, json={"siteEntry": [{"siteUrl": f"https://{host}/", "permissionLevel": "siteOwner"}]}
        )

    url = gsc.start(tid, wsite["owner"].id)
    assert "auth%2Fwebmasters" in url
    state = parse_qs(urlparse(url).query)["state"][0]
    with capture_logs() as logs:
        gsc.finish(db, "code", state, http=_mock(handler))
    db.commit()
    integ = gsc.connection(db, tid)
    assert decrypt_credentials(integ.credentials_kms_blob)["refresh_token"] == "rt-secret"
    dumped = json.dumps(integ.config) + json.dumps(gsc.status(db, tid)) + json.dumps(logs, default=str)
    assert "rt-secret" not in dumped and "at-secret" not in dumped
    assert integ.config["property"] == f"https://{host}/"
    assert puts and puts[0].endswith(f"sitemaps/https%3A%2F%2F{host}%2Fsitemap.xml")  # sitemap submitted once
    assert gsc.submit_sitemap_if_changed(db, tid) == "unchanged"
    with pytest.raises(MarketingError):
        gsc.finish(db, "code", state, http=_mock(handler))  # single-use state


def _gsc_handler(seen):
    def handler(req):
        body = json.loads(req.content or b"{}")
        seen.append(body)
        if req.method == "PUT":
            return httpx.Response(204)
        if body.get("dimensions") == ["date"]:
            return httpx.Response(
                200,
                json={
                    "rows": [{"keys": ["2026-11-06"], "clicks": 4, "impressions": 300, "ctr": 0.013, "position": 9.5}]
                },
            )

        def row(q, clicks):
            return {
                "keys": [q, "https://x/", "ind", "MOBILE"],
                "clicks": clicks,
                "impressions": 50,
                "ctr": 0.1,
                "position": 4.0,
            }

        return httpx.Response(
            200,
            json={
                "rows": [row("villa in coorg", 5), row("villa in coorg", 5), row("pool villa", 2), row("coorg stay", 1)]
            },
        )

    return handler


def test_gsc_pull_stores_totals_and_capped_rows_and_rerun_is_idempotent(db, wsite, monkeypatch):  # noqa: F811
    tid = wsite["tenant"].id
    _connect_gsc(db, tid)
    monkeypatch.setattr(sync, "GSC_ROWS_PER_DAY", 2)
    monkeypatch.setattr(sync, "GSC_BACKFILL_PER_RUN", 3)
    seen = []
    out = sync.pull_gsc(db, tid, TODAY, http=_mock(_gsc_handler(seen)))
    db.commit()
    assert out["more"] is True  # backfill continues next run
    detail = [b for b in seen if b.get("dimensions") == sync.GSC_DIMENSIONS]
    assert all(b["rowLimit"] == 2 for b in detail)
    days = sync.GSC_RECENT_DAYS + 3
    assert db.query(GscSearchRow).filter_by(tenant_id=tid).count() == days * 2  # duplicate dropped, cap of 2 per day
    t = db.query(GscDailyTotal).filter_by(tenant_id=tid).one()
    assert (t.clicks, t.impressions) == (4, 300)
    sync.pull_gsc(db, tid, TODAY, http=_mock(_gsc_handler([])))
    db.commit()
    assert (
        db.query(GscSearchRow).filter_by(tenant_id=tid, day=TODAY - timedelta(days=1)).count() == 2
    )  # same day, same rows
    assert db.query(GscDailyTotal).filter_by(tenant_id=tid).count() == 1
    st = gsc.connection(db, tid).config["metrics_pull"]
    assert st["backfill_until"] == (TODAY - timedelta(days=sync.GSC_RECENT_DAYS + 6)).isoformat()


def test_disconnect_deletes_api_data_only(db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    _connect_gbp(db, tid)
    _connect_gsc(db, tid)
    db.add_all(
        [
            GbpDailyMetric(tenant_id=tid, location="locations/9", day=TODAY, metric="CALL_CLICKS", value=2),
            GscDailyTotal(tenant_id=tid, property="sc-domain:example.com", day=TODAY, clicks=1, impressions=9),
            PageSpeedRun(tenant_id=tid, url="https://x/", strategy="mobile", week_of=TODAY),
        ]
    )
    db.commit()
    assert gsc.disconnect(db, tid, wsite["owner"].id)["deleted_totals"] == 1
    assert conns.disconnect(db, tid, "google_business", wsite["owner"].id)
    db.commit()
    assert db.query(GscDailyTotal).filter_by(tenant_id=tid).count() == 0
    assert db.query(GbpDailyMetric).filter_by(tenant_id=tid).count() == 0
    assert db.query(PageSpeedRun).filter_by(tenant_id=tid).count() == 1  # public API data, not from the connection
    assert gsc.connection(db, tid) is None


# ── Metrics ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_metrics_say_no_data_on_empty_and_never_compare_with_an_empty_period(db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    s = google_metrics.summary(db, tid, TODAY, 28)
    assert s["visibility"]["total"] is None and s["actions"]["total"] is None and s["visibility"]["change_pct"] is None
    assert s["period"]["to"] == "2026-11-07"  # ends yesterday
    db.add_all(
        [
            GbpDailyMetric(tenant_id=tid, location="l", day=date(2026, 11, 1), metric="CALL_CLICKS", value=3),
            GbpDailyMetric(
                tenant_id=tid, location="l", day=date(2026, 11, 1), metric="BUSINESS_IMPRESSIONS_DESKTOP_MAPS", value=40
            ),
        ]
    )
    db.commit()
    s = google_metrics.summary(db, tid, TODAY, 28)
    assert s["actions"]["calls"] == 3 and s["actions"]["search_clicks"] is None and s["actions"]["total"] == 3
    assert s["visibility"]["business_profile"] == 40 and s["visibility"]["search_results"] is None
    assert s["visibility"]["previous_total"] is None and s["visibility"]["change_pct"] is None  # no "-100%" / "+inf"
    assert google_metrics.change_pct(50, 100) == -50.0 and google_metrics.change_pct(5, 0) is None


def test_money_query_position_is_impression_weighted_and_tenant_scoped(db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    other = make_tenant(db, "Elsewhere")

    def row(t, q, pos, imps, day=date(2026, 11, 5)):
        return GscSearchRow(
            tenant_id=t,
            property="p",
            day=day,
            query=q,
            page="u",
            country="ind",
            device="MOBILE",
            impressions=imps,
            position=pos,
            row_key=f"{t}{q}{pos}{imps}",
        )

    db.add_all(
        [
            row(tid, "villa in coorg", 2.0, 30),
            row(tid, "villa in coorg", 6.0, 10),
            row(other.id, "villa in coorg", 50.0, 999),
        ]
    )
    db.commit()
    mq = google_metrics.summary(db, tid, TODAY, 28, money=["villa in coorg", "nothing yet"])["money_queries"]
    assert mq[0]["position"] == 3.0 and mq[0]["previous"] is None  # (2*30 + 6*10) / 40
    assert mq[1]["position"] is None and mq[1]["impressions"] is None
    assert (
        google_metrics.summary(db, other.id, TODAY, 28, money=["villa in coorg"])["money_queries"][0]["position"]
        == 50.0
    )


# ── PageSpeed ────────────────────────────────────────────────────────────────────────────────────────────────────────

PSI = {
    "loadingExperience": {"metrics": {}, "origin_fallback": True},
    "originLoadingExperience": {
        "overall_category": "AVERAGE",
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2900, "category": "AVERAGE"},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},
        },
    },
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.82}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 3120.4},
            "total-blocking-time": {"numericValue": 210},
            "cumulative-layout-shift": {"numericValue": 0.021},
        },
    },
}


def test_pagespeed_parses_field_and_lab_and_skips_without_key(db, client, wsite, monkeypatch):  # noqa: F811
    from app.models.tenant import Tenant
    from app.models.website import Site

    tid = wsite["tenant"].id
    assert sync.pull_pagespeed(db, db.get(Tenant, tid), None, TODAY) == {"skipped": "no_key"}
    publish_live(client, wsite)
    site = db.query(Site).filter_by(tenant_id=tid).one()
    db.refresh(site)
    monkeypatch.setattr("app.core.config.settings.PAGESPEED_API_KEY", "psi-key-secret")
    seen = []

    def handler(req):
        seen.append(req.url.params["strategy"])
        return httpx.Response(200, json=PSI)

    out = sync.pull_pagespeed(db, db.get(Tenant, tid), site, TODAY, http=_mock(handler))
    db.commit()
    assert out["failed"] == 0 and out["measured"] >= 2 and set(seen) == {"mobile", "desktop"}
    home = db.query(PageSpeedRun).filter_by(tenant_id=tid, label="Home", strategy="mobile").one()
    assert (home.lab_performance, home.lab_lcp_ms, home.field_lcp_ms, home.field_cls) == (82, 3120, 2900, 0.05)
    assert home.field_is_origin and home.field_category == "AVERAGE" and home.week_of == date(2026, 11, 2)
    seen.clear()
    sync.pull_pagespeed(db, db.get(Tenant, tid), site, TODAY, http=_mock(handler))
    assert seen == []  # once per page per week
    sp = google_metrics.speed(db, tid)
    assert sp["configured"] and sp["pages"][0]["mobile"]["verdict"] == "AVERAGE"


def test_pagespeed_error_never_carries_the_key(db):
    def handler(req):
        return httpx.Response(400, json={"error": {"message": "Bad key psi-key-secret for this url"}})

    with pytest.raises(sync.PublishError) as exc:
        sync.gs.run_pagespeed("https://x/", "mobile", "psi-key-secret", client=_mock(handler))
    assert "psi-key-secret" not in str(exc.value) and exc.value.status == 400


# ── Endpoints ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_google_endpoint_report_and_launch_report(client, db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    db.add(GscDailyTotal(tenant_id=tid, property="p", day=TODAY - timedelta(days=3), clicks=6, impressions=410))
    db.commit()
    r = client.get(GOOG, headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["search_console"]["connected"] is False and body["pagespeed"]["configured"] is False
    assert body["summary"]["visibility"]["search_results"] == 410
    rep = client.get(f"{BASE}/report?days=30", headers=wsite["owner_h"]).json()
    assert rep["google"]["actions"]["search_clicks"] == 6
    assert client.get(GOOG, headers=wsite["mkt_h"]).status_code == 200  # marketing may read
    assert client.get(GOOG, headers=wsite["foh_h"]).status_code == 403
    assert client.put(f"{GOOG}/money-queries", json={"queries": ["a"]}, headers=wsite["mkt_h"]).status_code == 403
    assert client.delete(f"{GOOG}/search-console", headers=wsite["foh_h"]).status_code == 403


def test_money_queries_and_property_are_per_workspace(client, db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    _connect_gsc(db, tid, prop="sc-domain:example.com")
    r = client.put(
        f"{GOOG}/money-queries",
        json={"queries": ["Villa in Coorg ", "villa in coorg", "pool villa"]},
        headers=wsite["owner_h"],
    )
    assert r.status_code == 200 and r.json()["money_queries"] == ["villa in coorg", "pool villa"]
    other = make_tenant(db, "Rival")
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user

    _, other_h = make_user(db, other.id, UserRole.OWNER)
    r = client.get(GOOG, headers=other_h)
    assert r.status_code == 200 and r.json()["search_console"]["connected"] is False  # never sees A's connection
    assert client.put(f"{GOOG}/money-queries", json={"queries": ["x"]}, headers=other_h).status_code == 409
    assert (
        client.put(
            f"{GOOG}/search-console/property", json={"property": "sc-domain:example.com"}, headers=other_h
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"{GOOG}/search-console/property", json={"property": "sc-domain:evil.com"}, headers=wsite["owner_h"]
        ).status_code
        == 404
    )
