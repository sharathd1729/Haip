"""Instagram content publishing with our Instagram-Login token (agency phase C).

Flow (developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing, read
18 Oct 2026): create a container (POST /{ig_id}/media with a public JPEG image_url), wait for status_code FINISHED,
then POST /{ig_id}/media_publish?creation_id=... Carousels: one child container per image (is_carousel_item), then a
CAROUSEL parent with children=... Stories: media_type=STORIES, one container per frame. There is no native
scheduling; the caller publishes at the slot. Quota: GET /{ig_id}/content_publishing_limit (docs say 50-100 per 24h;
we read it at runtime). Host pinned to graph.instagram.com; the token goes in the Authorization header.
"""
import time
from typing import Optional

import httpx

GRAPH = "https://graph.instagram.com/v21.0/"
_HOST = "graph.instagram.com"
TIMEOUT = 30
POLL_EVERY = 3
POLL_BUDGET = 90


class PublishError(Exception):
    """`transient`: safe to retry later (timeouts, 429, 5xx, container still in progress)."""

    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


class Publisher:
    def __init__(self, access_token: str, ig_user_id: str, client: Optional[httpx.Client] = None):
        self.token, self.ig = access_token, ig_user_id
        self._own = client is None
        self.c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)

    def close(self):
        if self._own:
            self.c.close()

    def _req(self, method: str, path: str, **params) -> dict:
        url = GRAPH + path
        if httpx.URL(url).host != _HOST:
            raise PublishError("refusing to call an unexpected host", transient=False)
        try:
            r = self.c.request(method, url, params=params or None, headers={"Authorization": f"Bearer {self.token}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise PublishError(f"Instagram did not answer: {type(exc).__name__}", transient=True) from exc
        if r.status_code != 200:
            transient = r.status_code == 429 or r.status_code >= 500
            try:
                code = (r.json().get("error") or {}).get("code")
            except ValueError:
                code = None
            transient = transient or code in (4, 17, 32, 613, 2)
            raise PublishError(f"Instagram {r.status_code}: {r.text[:300]}", transient=transient)
        return r.json()

    # ── steps ───────────────────────────────────────────────────────────────────────────────────────────────────────
    def quota_left(self) -> Optional[int]:
        data = self._req("GET", f"{self.ig}/content_publishing_limit", fields="quota_usage,config")
        row = (data.get("data") or [{}])[0]
        total = (row.get("config") or {}).get("quota_total")
        used = row.get("quota_usage")
        return None if total is None or used is None else max(int(total) - int(used), 0)

    def image_container(self, image_url: str, *, caption: Optional[str] = None, carousel_item: bool = False,
                        story: bool = False) -> str:
        params = {"image_url": image_url}
        if carousel_item:
            params["is_carousel_item"] = "true"
        if story:
            params["media_type"] = "STORIES"
        if caption and not carousel_item and not story:
            params["caption"] = caption
        return self._req("POST", f"{self.ig}/media", **params)["id"]

    def reel_container(self, video_url: str, *, caption: str, cover_url: Optional[str] = None) -> str:
        """A REELS container (agency M3): Instagram fetches the MP4 itself and takes minutes to process it, so
        wait_ready may raise a transient error; the caller keeps the container id and retries."""
        params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
        if cover_url:
            params["cover_url"] = cover_url
        return self._req("POST", f"{self.ig}/media", **params)["id"]

    def carousel_container(self, children: list[str], caption: str) -> str:
        return self._req("POST", f"{self.ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]

    def container_status(self, container_id: str) -> str:
        return self._req("GET", container_id, fields="status_code").get("status_code", "")

    def wait_ready(self, container_id: str) -> None:
        started = time.monotonic()
        while True:
            status = self.container_status(container_id)
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise PublishError(f"Instagram could not process the media ({status}).", transient=False)
            if time.monotonic() - started > POLL_BUDGET:
                raise PublishError("Instagram is still processing the media.", transient=True)
            time.sleep(POLL_EVERY)

    def publish(self, container_id: str) -> str:
        return self._req("POST", f"{self.ig}/media_publish", creation_id=container_id)["id"]

    def permalink(self, media_id: str) -> Optional[str]:
        try:
            return self._req("GET", media_id, fields="permalink").get("permalink")
        except PublishError:
            return None

    def comment(self, media_id: str, message: str) -> None:
        self._req("POST", f"{media_id}/comments", message=message)
