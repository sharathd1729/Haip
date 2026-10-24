"""Studio phase 2 (plan 24 Oct 2026): research sources off by default, keys named, fakes only (no outside call), the
logged-out collector with its fallback, hashtag allowance, media retention, rising sounds and the swipe file."""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.adapters.research import feeds, social
from app.core.config import settings
from app.models.audit_event import AuditEvent
from app.models.marketing import MarketingCompetitor, MarketingCompetitorPost
from app.models.marketing_research import MarketingSignal, MarketingSwipeItem
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_research_sources as src
from app.services import marketing_video_read as reader
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)

RSS = b"""<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
<item><title>Diwali trip</title><link>https://x/1</link><ht:approx_traffic>20,000+</ht:approx_traffic></item>
<item><title>Kabini</title><link>https://x/2</link><ht:approx_traffic>500+</ht:approx_traffic></item></channel></rss>"""


class _Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code, self.text = content, status, content.decode()


def _on(db, ws, **keys):  # noqa: F811
    src.put_settings(db, ws["tenant"], keys, ws["owner"].id)
    db.commit()


def _competitor(db, tid, handle="wildtrails"):
    c = MarketingCompetitor(tenant_id=tid, handle=handle, display_name="Wild Trails")
    db.add(c)
    db.commit()
    return c


# ── Switches ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_source_is_off_by_default_and_keys_are_named(db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "YOUTUBE_API_KEY", "")
    st = {s["key"]: s for s in src.status(db, ws["tenant"])}
    assert not any(s["on"] for s in st.values())
    assert st["youtube"]["missing_keys"] == ["YOUTUBE_API_KEY"] and st["audio"]["needs_facebook_login"]
    _on(db, ws, youtube=True)
    assert not src.ready(db, ws["tenant"], "youtube")                   # on, but the server has no key
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.research_sources.changed").count() == 1


def test_sources_api_owner_switches_and_tenant_isolation(client, db, ws):  # noqa: F811
    assert client.put(f"{BASE}/sources", json={"google_trends": True}, headers=ws["manager_h"]).status_code == 403
    assert client.put(f"{BASE}/sources", json={"nope": True}, headers=ws["owner_h"]).status_code == 422
    r = client.put(f"{BASE}/sources", json={"google_trends": True}, headers=ws["owner_h"])
    assert r.status_code == 200 and {s["key"]: s for s in r.json()["sources"]}["google_trends"]["ready"]
    db.add(MarketingSignal(tenant_id=ws["tenant"].id, source="google_trends", evidence="google", key="k", title="Ours",
                           observed_on=date.today()))
    db.commit()
    assert client.get(f"{BASE}/signals", headers=ws["mkt_h"]).json()["signals"][0]["title"] == "Ours"
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/signals", headers=other_h).json()["signals"] == []
    assert not any(s["on"] for s in client.get(f"{BASE}/sources", headers=other_h).json()["sources"])


# ── Feeds (parsing only; every call faked) ──────────────────────────────────────────────────────────────────────────

def test_google_trends_rss_is_parsed_with_traffic():
    rows = feeds.google_trends_daily(getter=lambda url, timeout, headers=None: _Resp(RSS))
    assert rows[0] == {"title": "Diwali trip", "url": "https://x/1", "published": None, "value": 20000}


def test_places_and_youtube_parse_and_pin_their_hosts():
    def handler(req: httpx.Request):
        if req.url.host == "places.googleapis.com":
            assert req.headers["X-Goog-Api-Key"] == "k"
            return httpx.Response(200, json={"places": [{"id": "P1", "displayName": {"text": "Wild Trails"}, "rating": 4.6,
                                                         "userRatingCount": 312, "reviews": [{"rating": 5, "text": {"text": "Clean, great view"}}]}]})
        assert req.url.host == "www.googleapis.com" and req.url.params["regionCode"] == "IN"
        return httpx.Response(200, json={"items": [{"id": "v1", "snippet": {"title": "Coorg in monsoon"}, "statistics": {"viewCount": "9000"}}]})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    p = feeds.places("k", "Wild Trails", client=c)[0]
    assert p["value"] == 312 and src.review_themes(p["reviews"]) == {"clean": 1, "view": 1}
    assert feeds.youtube_trending("k", client=c)[0]["value"] == 9000


def test_collect_signals_runs_only_switched_on_sources_and_survives_a_failure(db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(feeds, "google_trends_daily", lambda: [{"title": "Diwali trip", "url": "https://x/1", "value": 20000}])

    def broken(q):
        raise feeds.FeedError("News down", transient=True)
    monkeypatch.setattr(feeds, "google_news", broken)
    monkeypatch.setattr(feeds, "youtube_trending", lambda key: pytest.fail("youtube is off"))
    assert src.collect_signals(db, ws["tenant"]) == {}                   # nothing on, nothing called
    _on(db, ws, google_trends=True, google_news=True)
    ws["tenant"].brand_config = {**(ws["tenant"].brand_config or {}), "business_profile": {"city": "Coorg"},
                                 "marketing_studio": ws["tenant"].brand_config["marketing_studio"]}
    done = src.collect_signals(db, ws["tenant"])
    assert done["google_trends"] == 1 and str(done["google_news"]).startswith("failed")
    row = db.query(MarketingSignal).filter_by(tenant_id=ws["tenant"].id, source="google_trends").one()
    assert row.evidence == "google" and row.value == 20000


def test_hashtag_allowance_of_30_a_week_is_never_exceeded(db, ws, monkeypatch):  # noqa: F811
    for i in range(src.HASHTAGS_PER_WEEK):
        db.add(MarketingSignal(tenant_id=ws["tenant"].id, source="hashtag", evidence="platform", key=f"k{i}",
                               query=f"tag{i}", observed_on=date.today()))
    db.commit()
    asked = []
    monkeypatch.setattr(src, "_fb", lambda db, tid: ("tok", "IG1"))
    monkeypatch.setattr(src, "ready", lambda db, t, k: k == "hashtags")
    monkeypatch.setattr(feeds, "hashtag_top_media", lambda tok, ig, tag: asked.append(tag) or [])
    src.collect_signals(db, ws["tenant"], hashtags=["tag3", "newtag"])
    assert asked == ["tag3"]                                             # a used tag is free; a 31st is not asked


# ── Collector (logged out, fallback, retention) ─────────────────────────────────────────────────────────────────────

class _Blocked:
    name = "instaloader"

    def posts(self, handle, limit):
        raise social.SourceError("login required", blocked=True)


class _Apify:
    name = "apify"

    def __init__(self):
        self.calls = []

    def posts(self, handle, limit):
        self.calls.append((handle, limit))                               # a handle only: no token can reach it
        return [social._post(shortcode="ABC", url="https://www.instagram.com/p/ABC/", posted_at=datetime.now(timezone.utc).isoformat(),
                             caption="POV: Kabini #caravan", media_type="REELS", likes=50, comments=4, views=9000,
                             duration_s=14.0, audio="Sunrise song", video_url="https://cdn.example/v.mp4", thumb=None)]


def test_collector_falls_back_keeps_public_metadata_and_retains_media(db, ws, monkeypatch):  # noqa: F811
    tid = ws["tenant"].id
    comp = _competitor(db, tid)
    monkeypatch.setattr(settings, "RESEARCH_PROXY_URL", "socks5://proxy:1080")
    assert src.collect_competitors(db, ws["tenant"], chain=[_Apify()]) == {"skipped": "collector is off or not set up"}
    _on(db, ws, collector=True)
    stored = []
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", lambda t, data, mime, ext: stored.append(t) or f"{t}/m/1.mp4")
    apify = _Apify()
    out = src.collect_competitors(db, ws["tenant"], chain=[_Blocked(), apify], download=lambda url: b"video")
    db.commit()
    assert out["posts"] == 1 and out["provider"] == "apify" and apify.calls == [("wildtrails", src.POSTS_PER_COMPETITOR)]
    post = db.query(MarketingCompetitorPost).filter_by(competitor_id=comp.id).one()
    assert post.source == "apify" and post.audio_name == "Sunrise song" and post.hashtags == ["caravan"] and post.views == 9000
    assert post.media_key == f"{tid}/m/1.mp4" and stored == [tid]
    deleted = []
    monkeypatch.setattr("app.services.media_storage.delete_tenant_objects", lambda t, keys: deleted.extend(keys) or len(keys))
    assert src.sweep_media(db, now=datetime.now(timezone.utc) + timedelta(days=src.MEDIA_RETENTION_DAYS + 1)) == 1
    assert deleted == [f"{tid}/m/1.mp4"] and post.media_key is None


def test_rising_sounds_compare_two_windows(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    comp = _competitor(db, tid)
    today = date(2026, 10, 24)
    for i, (audio, days_ago) in enumerate([("Song A", 2), ("Song A", 3), ("Song A", 20), ("Song B", 20), ("Song B", 3)]):
        db.add(MarketingCompetitorPost(tenant_id=tid, competitor_id=comp.id, source="collector", media_id=f"m{i}",
                                       audio_name=audio, posted_at=(today - timedelta(days=days_ago)).isoformat()))
    db.commit()
    assert src.rising_sounds(db, tid, today) == [{"audio": "Song A", "uses": 2, "uses_before": 1}]


# ── Swipe file ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_cut_times_parse_ffmpeg_showinfo():
    class Out:
        stderr = "[Parsed_showinfo_1] n:0 pts:512 pts_time:1.2 ...\n[Parsed_showinfo_1] n:1 pts:1024 pts_time:3.85 ..."
    assert reader.cut_times(b"x", run=lambda *a, **k: Out()) == [1.2, 3.85]
    assert reader.pacing([1, 2, 3, 4, 5, 6, 7, 8], 14) == "fast" and reader.pacing([], 14) == "slow"


def test_reel_is_read_into_the_swipe_file(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    comp = _competitor(db, tid)
    post = MarketingCompetitorPost(tenant_id=tid, competitor_id=comp.id, source="collector", media_id="ABC",
                                   permalink="https://www.instagram.com/p/ABC/", media_key=f"{tid}/m/1.mp4", duration_s=10, views=5)
    db.add(post)
    db.commit()
    assert reader.to_read(db, tid) == [post.id]

    def describe(model, video, prompt, mime_type):
        assert mime_type == "video/mp4" and video == b"video"
        return ({"hook_text": "We woke up here", "hook_type": "pov", "shots": [{"what": "door opens"}], "cta": "DM us",
                 "extra": "dropped"}, {"provider": "gemini", "model": "gemini-3.6-flash"})
    item = reader.read_post(db, ws["tenant"], post.id, read_bytes=lambda k: b"video", describe=describe,
                            cutter=lambda v: [1.0, 2.0, 3.0])
    db.commit()
    assert item.status == "ready" and item.pacing == "medium" and "extra" not in item.reading
    assert reader.swipe_file(db, tid)[0]["hook_text"] == "We woke up here" and reader.to_read(db, tid) == []
    assert db.query(MarketingSwipeItem).filter_by(tenant_id=tid).count() == 1


# ── Collector isolation (it runs with backend/.env.collector: no ENCRYPTION_KEY, no AI keys) ────────────────────────

def test_collector_run_never_decrypts_a_tenant_token_and_hands_ai_to_the_normal_worker(db, ws, monkeypatch):  # noqa: F811
    from app.core.encryption import encrypt_credentials
    from app.models.integration import Integration
    from app.workers.tasks import marketing_research_tasks as tasks
    tid = ws["tenant"].id
    _competitor(db, tid)
    db.add(Integration(tenant_id=tid, kind="instagram_fb", status="active", config={"ig_user_id": "IG1"},
                       credentials_kms_blob=encrypt_credentials({"access_token": "secret"})))
    db.commit()
    monkeypatch.setattr(settings, "RESEARCH_PROXY_URL", "socks5://proxy:1080")
    monkeypatch.setattr(settings, "APIFY_TOKEN", "apify")
    _on(db, ws, collector=True, ad_library=True, video_reading=True, audio=True)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)              # as in the collector container

    def no_decrypt(*a, **k):
        raise AssertionError("the collector path must never decrypt a tenant token")
    monkeypatch.setattr("app.core.encryption.decrypt_credentials", no_decrypt)
    monkeypatch.setattr(src.social, "providers", lambda: [_Apify()])
    monkeypatch.setattr(src.social, "ApifyProvider", lambda: type("Ads", (), {"ads": lambda self, q, n: []})())
    monkeypatch.setattr("app.adapters.vision.gemini.describe", no_decrypt)   # no AI in the collector either
    queued = []
    monkeypatch.setattr(tasks.queue_reads, "delay", lambda *a: queued.append(a))
    out = tasks.collector_run(db, tid)
    assert out["posts"] == 1 and out["ads"] == 0 and queued == [(tid,)]
    assert db.query(MarketingSwipeItem).filter_by(tenant_id=tid).count() == 0
