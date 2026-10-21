"""Instagram Business Discovery: public numbers of another business/creator account (agency phase B).

Only available through "Instagram API with Facebook Login" (graph.facebook.com, a Facebook user token for a
Page-linked Instagram professional account), not through our Instagram-Login token. Needs instagram_basic +
instagram_manage_insights + pages_read_engagement and Meta App Review. Returns public fields only: followers,
media_count and recent media with like/comment counts, caption, type, time, permalink. No reach, saves or
impressions for other accounts (those are owner-only). Docs checked 18 Oct 2026:
https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery
"""
from typing import Optional

import httpx

GRAPH = "https://graph.facebook.com/v20.0/"
_HOST = "graph.facebook.com"
TIMEOUT = 20
MEDIA_LIMIT = 25
_MEDIA_FIELDS = "id,caption,like_count,comments_count,timestamp,media_type,permalink"


class DiscoveryError(Exception):
    """`kind`: not_found (handle not a business/creator account), bad_token, rate_limited, other."""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


def _classify(resp: httpx.Response) -> DiscoveryError:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    code, sub = err.get("code"), err.get("error_subcode")
    msg = err.get("message") or resp.text[:200]
    if resp.status_code == 429 or code in (4, 17, 32, 613):
        return DiscoveryError(f"Instagram rate limit: {msg}", "rate_limited")
    if resp.status_code in (401, 403) or code in (190, 102, 10, 200):
        return DiscoveryError(f"The Facebook connection was refused: {msg}", "bad_token")
    if code == 110 or sub == 2207013 or "Cannot find User" in msg:
        return DiscoveryError("That handle is not a public business or creator account.", "not_found")
    return DiscoveryError(f"Instagram API error {resp.status_code}: {msg}", "other")


def discover(access_token: str, ig_user_id: str, handle: str, *, client: Optional[httpx.Client] = None) -> dict:
    """Returns {"followers_count", "media_count", "username", "name", "media": [...]} for `handle`."""
    if not handle.replace(".", "").replace("_", "").isalnum():
        raise DiscoveryError("Not a valid handle.", "not_found")
    url = f"{GRAPH}{ig_user_id}"
    if httpx.URL(url).host != _HOST:
        raise DiscoveryError("refusing to call an unexpected host", "other")
    fields = (f"business_discovery.username({handle}){{username,name,followers_count,media_count,"
              f"media.limit({MEDIA_LIMIT}){{{_MEDIA_FIELDS}}}}}")
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        try:
            resp = c.get(url, params={"fields": fields}, headers={"Authorization": f"Bearer {access_token}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise DiscoveryError(f"Instagram did not answer: {type(exc).__name__}", "rate_limited") from exc
    finally:
        if own:
            c.close()
    if resp.status_code != 200:
        raise _classify(resp)
    bd = (resp.json() or {}).get("business_discovery") or {}
    media = (bd.get("media") or {}).get("data") or []
    return {"username": bd.get("username"), "name": bd.get("name"), "followers_count": bd.get("followers_count"),
            "media_count": bd.get("media_count"), "media": media}
