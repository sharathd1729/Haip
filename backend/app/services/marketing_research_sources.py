"""The researcher's outside sources (studio plan phase 2): per-workspace switches, collection, retention.

Every source is OFF until the OWNER switches it on (brand_config.marketing_studio.research_sources, audited) AND the
server has what it needs (keys named, never shown). Rows land in marketing_signals tagged own | platform | google; the
collector's competitor posts land in marketing_competitor_posts (source collector | apify).

Hard rules: the competitor collector runs only in the separate `research_collect` worker, logged out, through
RESEARCH_PROXY_URL, and never sees a tenant token (adapters/research/social.py takes a handle only). Official
Instagram calls (hashtags, audio) use the workspace's OWN Facebook Login connection (`instagram_fb`), as Business
Discovery does. Downloaded media is kept MEDIA_RETENTION_DAYS, then deleted by `sweep_media`.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.research import feeds
from app.adapters.research import social
from app.core.audit import append_audit
from app.core.config import settings
from app.models.integration import Integration
from app.models.marketing import MarketingCompetitor, MarketingCompetitorPost
from app.models.marketing_research import MarketingSignal
from app.models.tenant import Tenant
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

KEY = "research_sources"
POSTS_PER_COMPETITOR = 12
MAX_COMPETITORS = 15
MEDIA_RETENTION_DAYS = 30
MAX_MEDIA_BYTES = 20_000_000
HASHTAGS_PER_WEEK = 30           # Instagram's limit: 30 unique hashtags per account per 7 days
MAX_QUERIES = 5

# source -> (label, evidence, server keys needed, needs the Facebook Login connection)
SOURCES: dict[str, tuple[str, str, tuple[str, ...], bool]] = {
    "collector": ("Competitor Reels and posts (logged-out collector)", "platform", (), False),
    "ad_library": ("Competitor ads from the Meta Ad Library", "platform", ("APIFY_TOKEN",), False),
    "audio": ("Trending audio (Instagram)", "platform", (), True),
    "hashtags": ("Hashtag top posts (Instagram)", "platform", (), True),
    "youtube": ("YouTube trending travel videos in India", "platform", ("YOUTUBE_API_KEY",), False),
    "google_trends": ("Google Trends daily (India)", "google", (), False),
    "google_news": ("Google News for your destinations", "google", (), False),
    "places": ("Competitors' Google ratings and reviews", "google", ("GOOGLE_PLACES_API_KEY",), False),
    "keywords": ("Google search volumes (Keyword Planner)", "google", ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
                 "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID"), False),
    "video_reading": ("Read competitor Reels into the swipe file (AI video)", "platform", ("GEMINI_API_KEY",), False),
}
# Review words grouped into themes (Places): deterministic, explainable.
THEMES = {"clean": ("clean", "hygien", "tidy"), "view": ("view", "scenic", "sunrise", "sunset"),
          "food": ("food", "breakfast", "meal", "cook"), "staff": ("staff", "host", "service", "friendly"),
          "comfort": ("bed", "comfort", "ac ", "shower"), "price": ("price", "expensive", "value", "cost"),
          "noise": ("noise", "loud"), "location": ("location", "road", "far", "access")}


def get_settings(tenant: Optional[Tenant]) -> dict:
    section = ((tenant.brand_config or {}).get("marketing_studio") or {}) if tenant is not None else {}
    raw = section.get(KEY) if isinstance(section, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {k: bool(raw.get(k)) for k in SOURCES}


def put_settings(db: Session, tenant: Tenant, changes: dict, actor_id: str) -> dict:
    bad = [k for k in changes if k not in SOURCES or not isinstance(changes[k], bool)]
    if bad:
        raise MarketingError(422, "bad_sources", "Unknown source or not on/off.", bad)
    before = get_settings(tenant)
    after = {**before, **changes}
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    section[KEY] = after
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.research_sources.changed", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": after})
    return after


def _fb(db: Session, tenant_id: str) -> Optional[tuple[str, str]]:
    """(token, ig user id) of the workspace's own Facebook Login connection, or None."""
    from app.core.encryption import decrypt_credentials
    integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram_fb", status="active").first()
    if integ is None or not integ.credentials_kms_blob:
        return None
    creds = decrypt_credentials(integ.credentials_kms_blob)
    ig = (integ.config or {}).get("ig_user_id") or (integ.config or {}).get("instagram_business_account_id") or creds.get("ig_user_id")
    return (creds.get("access_token"), ig) if creds.get("access_token") and ig else None


def _state(key: str, on: bool, fb_ok: Callable[[], bool]) -> dict:
    """One source's status. `fb_ok` (which decrypts the Facebook Login token) is called ONLY for a source that needs
    that connection, so the collector path (collector, ad_library) never touches a tenant token."""
    label, evidence, keys, needs_fb = SOURCES[key]
    missing = [k for k in keys if not getattr(settings, k, "")]
    if key == "collector" and not settings.RESEARCH_PROXY_URL:
        missing.append("RESEARCH_PROXY_URL")
    no_fb = needs_fb and not fb_ok()
    return {"key": key, "label": label, "evidence": evidence, "on": on, "missing_keys": missing,
            "needs_facebook_login": no_fb, "ready": on and not missing and not no_fb}


def status(db: Session, tenant: Tenant) -> list[dict]:
    on = get_settings(tenant)
    cache: dict = {}

    def fb_ok() -> bool:
        if "fb" not in cache:
            cache["fb"] = _fb(db, tenant.id) is not None
        return cache["fb"]
    return [_state(key, on[key], fb_ok) for key in SOURCES]


def ready(db: Session, tenant: Tenant, key: str) -> bool:
    return _state(key, get_settings(tenant)[key], lambda: _fb(db, tenant.id) is not None)["ready"]


def queries(db: Session, tenant: Tenant) -> list[str]:
    """What to ask Google about: the published destinations, else the profile's city / region."""
    names: list[str] = []
    try:
        from app.services import business_data_service as bds
        names = [r.data.get("name") for r in bds.list_effective(db, tenant.id, "destination") if (r.data or {}).get("name")]
    except Exception as exc:  # noqa: BLE001 -- destinations are optional context
        log.info("research_destinations_unavailable", error=type(exc).__name__)
    prof = ((tenant.brand_config or {}).get("business_profile") or {})
    names += [prof.get("city"), prof.get("region")]
    seen, out = set(), []
    for n in names:
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:MAX_QUERIES]


def _store(db: Session, tenant_id: str, source: str, rows: list[dict], *, query: Optional[str] = None,
           key_of: Callable[[dict], str] = lambda r: r.get("url") or r.get("title") or "", today: Optional[date] = None) -> int:
    day = today or date.today()
    evidence = SOURCES.get(source, ("", "platform"))[1]
    n = 0
    for r in rows:
        key = str(key_of(r) or "")[:200]
        if not key:
            continue
        row = db.query(MarketingSignal).filter_by(tenant_id=tenant_id, source=source, key=key, observed_on=day).first()
        if row is None:
            row = MarketingSignal(tenant_id=tenant_id, source=source, evidence=evidence, key=key, observed_on=day)
            db.add(row)
        row.title, row.url, row.value, row.query = (r.get("title") or r.get("name")), r.get("url"), r.get("value"), query
        row.data = {k: v for k, v in r.items() if k not in ("title", "url", "value")}
        n += 1
    db.flush()
    return n


def review_themes(reviews: list[dict]) -> dict:
    out: Counter = Counter()
    for r in reviews:
        text = f" {(r.get('text') or '').lower()} "
        for theme, words in THEMES.items():
            if any(w in text for w in words):
                out[theme] += 1
    return dict(out.most_common())


def hashtags_used_this_week(db: Session, tenant_id: str) -> set[str]:
    since = date.today() - timedelta(days=6)
    return {q for (q,) in db.query(MarketingSignal.query).filter(MarketingSignal.tenant_id == tenant_id,
                                                                  MarketingSignal.source == "hashtag",
                                                                  MarketingSignal.observed_on >= since) if q}


def collect_signals(db: Session, tenant: Tenant, *, hashtags: Optional[list[str]] = None) -> dict:
    """Every switched-on official/open source, once. A failing source is logged and skipped; the rest still run."""
    done: dict[str, object] = {}
    qs = queries(db, tenant)

    def run(key: str, fn: Callable[[], int]) -> None:
        if not ready(db, tenant, key):
            return
        try:
            done[key] = fn()
        except (feeds.FeedError, social.SourceError) as exc:
            done[key] = f"failed: {exc}"[:200]
            log.warning("research_source_failed", tenant_id=tenant.id, source=key, error=str(exc)[:200])

    run("google_trends", lambda: _store(db, tenant.id, "google_trends", feeds.google_trends_daily()))
    run("google_news", lambda: sum(_store(db, tenant.id, "google_news", feeds.google_news(q), query=q) for q in qs))
    run("youtube", lambda: _store(db, tenant.id, "youtube", feeds.youtube_trending(settings.YOUTUBE_API_KEY)))

    def places() -> int:
        n = 0
        for c in db.query(MarketingCompetitor).filter_by(tenant_id=tenant.id, active=1).limit(MAX_COMPETITORS):
            rows = feeds.places(settings.GOOGLE_PLACES_API_KEY, c.display_name or c.handle)
            for r in rows:
                r["themes"] = review_themes(r.get("reviews") or [])
            n += _store(db, tenant.id, "places", rows[:1], query=c.handle, key_of=lambda r: r.get("place_id"))
        return n
    run("places", places)
    run("keywords", lambda: _store(db, tenant.id, "keywords", feeds.keyword_volumes(
        [k for q in qs for k in (f"{q} trip", f"{q} weekend getaway", f"caravan {q}")]), key_of=lambda r: r.get("title")))
    fb = _fb(db, tenant.id)
    if fb:
        run("audio", lambda: _store(db, tenant.id, "audio", feeds.trending_audio(*fb), key_of=lambda r: r.get("key")))

        def tags() -> int:
            used = hashtags_used_this_week(db, tenant.id)
            n = 0
            for tag in hashtags or _default_hashtags(tenant):
                tag = tag.lstrip("#").lower()
                if tag not in used and len(used) >= HASHTAGS_PER_WEEK:
                    break                       # the weekly allowance is spent: never ask Instagram for a 31st tag
                used.add(tag)
                n += _store(db, tenant.id, "hashtag", feeds.hashtag_top_media(*fb, tag), query=tag)
            return n
        run("hashtags", tags)
    return done


def _default_hashtags(tenant: Tenant) -> list[str]:
    prof = ((tenant.brand_config or {}).get("business_profile") or {})
    return [h for h in (prof.get("default_hashtags") or [])][:5]


# ── Competitor collector (research_collect queue only) ─────────────────────────────────────────────────────────────

def collect_competitors(db: Session, tenant: Tenant, *, chain: Optional[list] = None,
                        download: Optional[Callable[[str], bytes]] = None) -> dict:
    """Public posts of each listed competitor, logged out. Upserts by (competitor, shortcode); keeps a copy of Reel
    videos (<= MAX_MEDIA_BYTES) for MEDIA_RETENTION_DAYS so the video reader can analyse them."""
    if not ready(db, tenant, "collector"):
        return {"skipped": "collector is off or not set up"}
    out = {"competitors": 0, "posts": 0, "provider": None, "errors": []}
    for comp in db.query(MarketingCompetitor).filter_by(tenant_id=tenant.id, active=1).limit(MAX_COMPETITORS):
        try:
            provider, posts = social.posts_with_fallback(comp.handle, POSTS_PER_COMPETITOR, chain)
        except social.SourceError as exc:
            out["errors"].append(f"@{comp.handle}: {exc}"[:200])
            continue
        out["competitors"] += 1
        out["provider"] = provider
        for p in posts:
            if not p.get("shortcode"):
                continue
            row = db.query(MarketingCompetitorPost).filter_by(tenant_id=tenant.id, competitor_id=comp.id,
                                                              media_id=p["shortcode"]).first()
            if row is None:
                row = MarketingCompetitorPost(tenant_id=tenant.id, competitor_id=comp.id, media_id=p["shortcode"],
                                              source="collector" if provider == "instaloader" else "apify")
                db.add(row)
            row.permalink, row.caption, row.media_type = p["permalink"], p["caption"], p["media_type"]
            row.like_count, row.comments_count, row.views = p["likes"], p["comments"], p["views"]
            row.posted_at, row.duration_s, row.audio_name, row.hashtags = p["posted_at"], p["duration_s"], p["audio_name"], p["hashtags"]
            row.media_url = p["media_url"]
            if download and p["media_type"] == "REELS" and p["media_url"] and not row.media_key:
                _keep_media(tenant.id, row, download)
            out["posts"] += 1
        db.flush()
    return out


def _keep_media(tenant_id: str, row: MarketingCompetitorPost, download: Callable[[str], bytes]) -> None:
    from app.services.media_storage import upload_marketing_media
    try:
        data = download(row.media_url)
    except Exception as exc:  # noqa: BLE001 -- media is optional; metadata is still kept
        log.info("research_media_not_kept", tenant_id=tenant_id, error=type(exc).__name__)
        return
    if not data or len(data) > MAX_MEDIA_BYTES:
        return
    row.media_key = upload_marketing_media(tenant_id, data, "video/mp4", "mp4")
    row.media_expires_at = datetime.now(timezone.utc) + timedelta(days=MEDIA_RETENTION_DAYS)


def download_public(url: str) -> bytes:
    """GET a public media URL through the SSRF guard (and the research proxy when set), size-capped."""
    from app.core.url_safety import assert_public_url
    import httpx
    assert_public_url(url, allow_http=False)
    proxy = settings.RESEARCH_PROXY_URL or None
    with httpx.Client(timeout=60, follow_redirects=False, proxy=proxy) as c:
        with c.stream("GET", url) as resp:
            resp.raise_for_status()
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf += chunk
                if len(buf) > MAX_MEDIA_BYTES:
                    raise ValueError("media too large")
            return bytes(buf)


def collect_ads(db: Session, tenant: Tenant, *, provider=None) -> int:
    if not ready(db, tenant, "ad_library"):
        return 0
    p = provider or social.ApifyProvider()
    n = 0
    for comp in db.query(MarketingCompetitor).filter_by(tenant_id=tenant.id, active=1).limit(MAX_COMPETITORS):
        rows = p.ads(comp.display_name or comp.handle, 10)
        n += _store(db, tenant.id, "ad_library", [{**r, "title": r.get("title") or (r.get("body") or "")[:120]} for r in rows],
                    query=comp.handle, key_of=lambda r: r.get("ad_id"))
    return n


def rising_sounds(db: Session, tenant_id: str, today: Optional[date] = None, days: int = 14) -> list[dict]:
    """Audio names on competitor Reels: posts in the last `days` vs the `days` before (our own rising-sound count)."""
    today = today or date.today()
    cut, start = (today - timedelta(days=days)).isoformat(), (today - timedelta(days=2 * days)).isoformat()
    now, before = Counter(), Counter()
    for audio, posted in db.query(MarketingCompetitorPost.audio_name, MarketingCompetitorPost.posted_at).filter(
            MarketingCompetitorPost.tenant_id == tenant_id, MarketingCompetitorPost.audio_name.isnot(None)):
        d = (posted or "")[:10]
        if d >= cut:
            now[audio] += 1
        elif d >= start:
            before[audio] += 1
    return sorted(({"audio": a, "uses": n, "uses_before": before[a]} for a, n in now.items() if n > before[a]),
                  key=lambda x: -(x["uses"] - x["uses_before"]))[:10]


def sweep_media(db: Session, now: Optional[datetime] = None) -> int:
    """Delete kept competitor media past its retention date (storage + key)."""
    from app.services.media_storage import delete_tenant_objects
    now = now or datetime.now(timezone.utc)
    rows = (db.query(MarketingCompetitorPost).filter(MarketingCompetitorPost.media_key.isnot(None),
                                                     MarketingCompetitorPost.media_expires_at < now).limit(500).all())
    by_tenant: dict[str, list] = {}
    for r in rows:
        by_tenant.setdefault(r.tenant_id, []).append(r)
    for tid, rs in by_tenant.items():
        delete_tenant_objects(tid, [r.media_key for r in rs])
        for r in rs:
            r.media_key, r.media_expires_at = None, None
    return len(rows)
