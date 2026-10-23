"""Competitor collector (studio plan phase 2): PUBLIC posts of public Instagram accounts, logged out.

Runs only in the separate, opt-in `research_collector` worker (Celery queue `research_collect`, docker-compose profile
`research`), never in the API or the main worker. It never logs in and never receives any tenant's Instagram or Facebook
token or HAIP's Meta app credentials: the functions below take a handle, nothing else. Egress goes through
RESEARCH_PROXY_URL when set.

Two providers, one interface (`posts(handle, limit) -> list[dict]`, `ads(query, limit)`):
  * instaloader (MIT; requirements-collector.txt, installed only in the collector image): logged-out profile posts.
    It gives the Reel's video URL too, so no separate downloader (yt-dlp) is needed.
  * Apify (APIFY_TOKEN; actors apify/instagram-scraper and apify/facebook-ads-scraper): the fallback when instaloader
    is blocked, and the only path for the Meta Ad Library (active ads only; India shows no spend).
Only public metadata is returned: shortcode, permalink, time, caption, type, likes, comments, views, length, audio
name, hashtags, and the media URL for analysis (downloaded through the SSRF guard, kept for a limited time).
"""
import re
from datetime import timezone
from typing import Optional, Protocol
from urllib.parse import quote

import httpx

from app.core.config import settings

APIFY = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
_APIFY_HOST = "api.apify.com"
_HASHTAG = re.compile(r"#(\w+)")
TIMEOUT = 120


class SourceError(Exception):
    def __init__(self, message: str, *, transient: bool = False, blocked: bool = False):
        super().__init__(message)
        self.transient, self.blocked = transient, blocked


class Provider(Protocol):
    name: str

    def posts(self, handle: str, limit: int) -> list[dict]: ...

    def ads(self, query: str, limit: int) -> list[dict]: ...


def _post(*, shortcode, url, posted_at, caption, media_type, likes, comments, views, duration_s, audio, video_url,
          thumb) -> dict:
    return {"shortcode": shortcode, "permalink": url, "posted_at": posted_at, "caption": (caption or "")[:2200],
            "media_type": media_type, "likes": likes, "comments": comments, "views": views, "duration_s": duration_s,
            "audio_name": (audio or None) and str(audio)[:200], "hashtags": sorted(set(_HASHTAG.findall(caption or "")))[:30],
            "media_url": video_url or thumb}


class InstaloaderProvider:
    name = "instaloader"

    def __init__(self, loader=None):
        self._loader = loader

    def _client(self):
        if self._loader is None:
            try:
                import instaloader  # noqa: PLC0415 -- only installed in the collector image
            except ImportError as exc:
                raise SourceError("instaloader is not installed in this worker (collector image only).") from exc
            self._loader = instaloader.Instaloader(download_pictures=False, download_videos=False, save_metadata=False,
                                                   quiet=True, max_connection_attempts=1)
            if settings.RESEARCH_PROXY_URL:
                self._loader.context._session.proxies = {"http": settings.RESEARCH_PROXY_URL,
                                                         "https": settings.RESEARCH_PROXY_URL}
        return self._loader

    def posts(self, handle: str, limit: int) -> list[dict]:
        import itertools
        loader = self._client()
        try:
            import instaloader  # noqa: PLC0415
            profile = instaloader.Profile.from_username(loader.context, handle)
            out = []
            for p in itertools.islice(profile.get_posts(), limit):
                out.append(_post(shortcode=p.shortcode, url=f"https://www.instagram.com/p/{p.shortcode}/",
                                 posted_at=p.date_utc.replace(tzinfo=timezone.utc).isoformat(), caption=p.caption,
                                 media_type="REELS" if p.is_video and getattr(p, "product_type", "") == "clips"
                                 else ("VIDEO" if p.is_video else ("CAROUSEL_ALBUM" if p.typename == "GraphSidecar" else "IMAGE")),
                                 likes=p.likes, comments=p.comments, views=p.video_view_count if p.is_video else None,
                                 duration_s=getattr(p, "video_duration", None), audio=None,
                                 video_url=p.video_url if p.is_video else None, thumb=p.url))
            return out
        except SourceError:
            raise
        except Exception as exc:  # noqa: BLE001 -- instaloader raises many types; login walls / 429 = blocked
            text = str(exc)
            raise SourceError(f"instaloader: {type(exc).__name__}: {text[:200]}",
                              blocked=any(k in text.lower() for k in ("login", "429", "please wait", "checkpoint")),
                              transient=True) from exc

    def ads(self, query: str, limit: int) -> list[dict]:
        raise SourceError("The Ad Library is read through Apify only.")


class ApifyProvider:
    name = "apify"

    def __init__(self, token: Optional[str] = None, client: Optional[httpx.Client] = None):
        self.token = token or settings.APIFY_TOKEN
        self._client = client

    def _run(self, actor: str, body: dict) -> list[dict]:
        if not self.token:
            raise SourceError("APIFY_TOKEN is not set.")
        url = APIFY.format(actor=actor)
        if httpx.URL(url).host != _APIFY_HOST:
            raise SourceError("refusing to call an unexpected host")
        c = self._client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        try:
            resp = c.post(url, json=body, headers={"Authorization": f"Bearer {self.token}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise SourceError(f"Apify did not answer: {type(exc).__name__}", transient=True) from exc
        finally:
            if self._client is None:
                c.close()
        if resp.status_code >= 400:
            raise SourceError(f"Apify {resp.status_code}: {resp.text[:200]}", transient=resp.status_code >= 500)
        data = resp.json()
        return data if isinstance(data, list) else []

    def posts(self, handle: str, limit: int) -> list[dict]:
        rows = self._run("apify~instagram-scraper", {"directUrls": [f"https://www.instagram.com/{handle}/"],
                                                     "resultsType": "posts", "resultsLimit": limit})
        out = []
        for r in rows[:limit]:
            kind = {"Video": "VIDEO", "Sidecar": "CAROUSEL_ALBUM", "Image": "IMAGE"}.get(r.get("type"), r.get("type"))
            if r.get("productType") == "clips":
                kind = "REELS"
            music = r.get("musicInfo") or {}
            out.append(_post(shortcode=r.get("shortCode"), url=r.get("url"), posted_at=r.get("timestamp"),
                             caption=r.get("caption"), media_type=kind, likes=r.get("likesCount"),
                             comments=r.get("commentsCount"), views=r.get("videoViewCount") or r.get("videoPlayCount"),
                             duration_s=r.get("videoDuration"), audio=music.get("song_name") or music.get("audio_id"),
                             video_url=r.get("videoUrl"), thumb=r.get("displayUrl")))
        return out

    def ads(self, query: str, limit: int) -> list[dict]:
        url = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=IN&q=" + quote(query)
        rows = self._run("apify~facebook-ads-scraper", {"startUrls": [{"url": url}], "resultsLimit": limit})
        out = []
        for r in rows[:limit]:
            snap = r.get("snapshot") or {}
            out.append({"ad_id": str(r.get("adArchiveID") or r.get("ad_archive_id") or ""),
                        "page_name": r.get("pageName") or snap.get("page_name"),
                        "started": r.get("startDateFormatted") or r.get("start_date"),
                        "body": ((snap.get("body") or {}).get("text") if isinstance(snap.get("body"), dict) else snap.get("body")),
                        "title": snap.get("title"), "cta": snap.get("cta_text"),
                        "platforms": r.get("publisherPlatform") or r.get("publisher_platform")})
        return out


def providers() -> list[Provider]:
    """In order of preference; Apify only when its token is set."""
    out: list[Provider] = [InstaloaderProvider()]
    if settings.APIFY_TOKEN:
        out.append(ApifyProvider())
    return out


def posts_with_fallback(handle: str, limit: int, chain: Optional[list[Provider]] = None) -> tuple[str, list[dict]]:
    """(provider name, posts): the first provider that answers. Raises the last SourceError if none does."""
    last: Optional[SourceError] = None
    for p in chain if chain is not None else providers():
        try:
            return p.name, p.posts(handle, limit)
        except SourceError as exc:
            last = exc
    raise last or SourceError("No collector is available.")

