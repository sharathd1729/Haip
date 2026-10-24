"""Official / open research sources (studio plan phase 2). Every call is host-pinned and goes through the SSRF guard;
each returns plain dicts and raises FeedError. Nothing here runs unless the workspace switched that source on AND the
server has its key (services/marketing_research_sources.py).

  google      Google Trends daily RSS (geo IN, no key), Google News RSS (search, no key), Google Places API (New) text
              search (GOOGLE_PLACES_API_KEY), Keyword Planner historical volumes via the Google Ads API
              (GOOGLE_ADS_DEVELOPER_TOKEN + OAuth client + refresh token + customer id)
  platform    YouTube Data API most-popular Travel & Events in India (YOUTUBE_API_KEY); Instagram hashtag search + top
              media, and trending audio (both through the workspace's Facebook Login connection `instagram_fb`)
Pinterest Trends is not built: it needs a Pinterest app + business OAuth per workspace (owner decision pending).
"""
from typing import Optional
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

import httpx

from app.core.config import settings
from app.core.url_safety import UnsafeURLError, safe_get

TIMEOUT = 20
MAX_BYTES = 2_000_000
GOOGLE_ADS_VERSION = "v19"          # unverified against a live call: confirm before switching keyword volumes on
GEO_INDIA = "geoTargetConstants/2356"
LANG_EN = "languageConstants/1000"
GRAPH = "https://graph.facebook.com/v20.0/"
_HT = "{https://trends.google.com/trending/rss}"


class FeedError(Exception):
    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def _check(resp: httpx.Response, who: str) -> httpx.Response:
    if resp.status_code >= 400:
        raise FeedError(f"{who} {resp.status_code}: {resp.text[:200]}", transient=resp.status_code == 429 or resp.status_code >= 500)
    if len(resp.content) > MAX_BYTES:
        raise FeedError(f"{who}: answer too large")
    return resp


def _get(url: str, who: str, headers: Optional[dict] = None, getter=None) -> httpx.Response:
    try:
        return _check((getter or safe_get)(url, timeout=TIMEOUT, headers=headers), who)
    except UnsafeURLError as exc:
        raise FeedError(f"{who}: {exc}") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise FeedError(f"{who} did not answer: {type(exc).__name__}", transient=True) from exc


def _rss(xml: bytes) -> list[ElementTree.Element]:
    try:
        return ElementTree.fromstring(xml).findall("./channel/item")
    except ElementTree.ParseError as exc:
        raise FeedError(f"Unreadable RSS: {exc}") from exc


def google_trends_daily(geo: str = "IN", getter=None) -> list[dict]:
    resp = _get(f"https://trends.google.com/trending/rss?geo={quote(geo)}", "Google Trends", getter=getter)
    out = []
    for item in _rss(resp.content):
        traffic = (item.findtext(f"{_HT}approx_traffic") or "").replace(",", "").replace("+", "")
        out.append({"title": item.findtext("title"), "url": item.findtext("link"), "published": item.findtext("pubDate"),
                    "value": int(traffic) if traffic.isdigit() else None})
    return out


def google_news(query: str, getter=None) -> list[dict]:
    q = urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    resp = _get(f"https://news.google.com/rss/search?{q}", "Google News", getter=getter)
    return [{"title": i.findtext("title"), "url": i.findtext("link"), "published": i.findtext("pubDate"),
             "source": i.findtext("source")} for i in _rss(resp.content)[:20]]


def youtube_trending(api_key: str, client: Optional[httpx.Client] = None) -> list[dict]:
    """Most popular Travel & Events (category 19) videos in India."""
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        resp = _check(c.get("https://www.googleapis.com/youtube/v3/videos", params={
            "part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": "IN",
            "videoCategoryId": "19", "maxResults": 25, "key": api_key}), "YouTube")
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise FeedError(f"YouTube did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()
    out = []
    for v in resp.json().get("items", []):
        s, st = v.get("snippet") or {}, v.get("statistics") or {}
        out.append({"title": s.get("title"), "url": f"https://www.youtube.com/watch?v={v.get('id')}",
                    "channel": s.get("channelTitle"), "published": s.get("publishedAt"), "tags": (s.get("tags") or [])[:15],
                    "value": int(st["viewCount"]) if str(st.get("viewCount", "")).isdigit() else None})
    return out


def places(api_key: str, query: str, client: Optional[httpx.Client] = None) -> list[dict]:
    """Ratings, review counts and up to 5 review texts per place (Places API New, text search)."""
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        resp = _check(c.post("https://places.googleapis.com/v1/places:searchText", json={"textQuery": query, "regionCode": "IN"},
                             headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask":
                                      "places.id,places.displayName,places.rating,places.userRatingCount,places.reviews,places.googleMapsUri"}),
                      "Google Places")
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise FeedError(f"Google Places did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()
    out = []
    for p in resp.json().get("places", [])[:5]:
        out.append({"place_id": p.get("id"), "name": (p.get("displayName") or {}).get("text"), "url": p.get("googleMapsUri"),
                    "rating": p.get("rating"), "value": p.get("userRatingCount"),
                    "reviews": [{"rating": r.get("rating"), "text": ((r.get("text") or {}).get("text") or "")[:600]}
                                for r in (p.get("reviews") or [])[:5]]})
    return out


def keyword_volumes(keywords: list[str], client: Optional[httpx.Client] = None) -> list[dict]:
    """Average monthly Google searches in India per keyword (Keyword Planner, Google Ads API)."""
    s = settings
    if not all((s.GOOGLE_ADS_DEVELOPER_TOKEN, s.GOOGLE_ADS_CLIENT_ID, s.GOOGLE_ADS_CLIENT_SECRET,
                s.GOOGLE_ADS_REFRESH_TOKEN, s.GOOGLE_ADS_CUSTOMER_ID)):
        raise FeedError("Google Ads keys are not set.")
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        tok = _check(c.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "refresh_token", "refresh_token": s.GOOGLE_ADS_REFRESH_TOKEN,
            "client_id": s.GOOGLE_ADS_CLIENT_ID, "client_secret": s.GOOGLE_ADS_CLIENT_SECRET}), "Google OAuth").json()
        cid = "".join(ch for ch in s.GOOGLE_ADS_CUSTOMER_ID if ch.isdigit())
        resp = _check(c.post(f"https://googleads.googleapis.com/{GOOGLE_ADS_VERSION}/customers/{cid}:generateKeywordHistoricalMetrics",
                             json={"keywords": keywords[:50], "geoTargetConstants": [GEO_INDIA], "language": LANG_EN,
                                   "keywordPlanNetwork": "GOOGLE_SEARCH"},
                             headers={"Authorization": f"Bearer {tok.get('access_token')}",
                                      "developer-token": s.GOOGLE_ADS_DEVELOPER_TOKEN}), "Google Ads")
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise FeedError(f"Google Ads did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()
    out = []
    for r in resp.json().get("results", []):
        m = r.get("keywordMetrics") or {}
        v = m.get("avgMonthlySearches")
        out.append({"title": r.get("text"), "value": int(v) if str(v or "").isdigit() else None,
                    "competition": m.get("competition")})
    return out


def _graph(token: str, path: str, params: dict, client: Optional[httpx.Client]) -> dict:
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        return _check(c.get(GRAPH + path, params={**params, "access_token": token}), "Instagram").json()
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise FeedError(f"Instagram did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if client is None:
            c.close()


def hashtag_top_media(token: str, ig_user_id: str, tag: str, client: Optional[httpx.Client] = None) -> list[dict]:
    """Top public posts for a hashtag. Instagram allows 30 unique hashtags per account per 7 days (tracked by the caller)."""
    found = _graph(token, "ig_hashtag_search", {"user_id": ig_user_id, "q": tag.lstrip("#")}, client).get("data") or []
    if not found:
        return []
    rows = _graph(token, f"{found[0]['id']}/top_media", {"user_id": ig_user_id, "limit": 25, "fields":
                  "id,caption,media_type,like_count,comments_count,permalink,timestamp"}, client).get("data") or []
    return [{"title": (r.get("caption") or "")[:200], "url": r.get("permalink"), "published": r.get("timestamp"),
             "media_type": r.get("media_type"), "value": (r.get("like_count") or 0) + (r.get("comments_count") or 0)}
            for r in rows]


def trending_audio(token: str, ig_user_id: str, client: Optional[httpx.Client] = None) -> list[dict]:
    """Instagram's licensed trending audio (owner's spec: GET /ig_audio, trending by default, through the Facebook Login
    connection). UNVERIFIED against a live call: keep the source off until one succeeds."""
    rows = _graph(token, "ig_audio", {"user_id": ig_user_id, "fields": "id,title,artist,duration_ms"}, client).get("data") or []
    return [{"key": str(r.get("id")), "title": r.get("title"), "artist": r.get("artist"),
             "duration_ms": r.get("duration_ms")} for r in rows if r.get("id")]
