"""Facebook Page publishing with a Page access token (agency M3).

Graph API (developers.facebook.com/docs/pages-api/posts, read 21 Oct 2026): a single photo post is POST /{page_id}/photos
with `url` (a public JPEG) and `message`; it returns the photo `id` and the `post_id`. Several photos: upload each with
`published=false` (returns its id), then POST /{page_id}/feed with `message` and `attached_media` = [{"media_fbid": id}].
Permissions on the Page token: pages_manage_posts + pages_read_engagement (Meta App Review). Host pinned to
graph.facebook.com; the token goes in the Authorization header. Errors use the Instagram publisher's PublishError.
"""
import json
from typing import Optional

import httpx

from app.adapters.instagram.publishing import PublishError

GRAPH = "https://graph.facebook.com/v20.0/"
_HOST = "graph.facebook.com"
TIMEOUT = 30


class FacebookPage:
    def __init__(self, page_token: str, page_id: str, client: Optional[httpx.Client] = None):
        if not page_token or not page_id:
            raise PublishError("Facebook Page is not connected for this workspace.", transient=False)
        self.token, self.page = page_token, page_id
        self._own = client is None
        self.c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)

    def close(self) -> None:
        if self._own:
            self.c.close()

    def _req(self, method: str, path: str, data: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        url = GRAPH + path
        if httpx.URL(url).host != _HOST:
            raise PublishError("refusing to call an unexpected host", transient=False)
        try:
            r = self.c.request(method, url, data=data, params=params, headers={"Authorization": f"Bearer {self.token}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise PublishError(f"Facebook did not answer: {type(exc).__name__}", transient=True) from exc
        if r.status_code != 200:
            try:
                code = (r.json().get("error") or {}).get("code")
            except ValueError:
                code = None
            raise PublishError(f"Facebook {r.status_code}: {r.text[:300]}",
                               transient=r.status_code == 429 or r.status_code >= 500 or code in (1, 2, 4, 17, 32, 613))
        return r.json()

    def photo_post(self, image_url: str, message: str) -> str:
        """One photo, published now. Returns the post id."""
        data = self._req("POST", f"{self.page}/photos", data={"url": image_url, "message": message, "published": "true"})
        return data.get("post_id") or data["id"]

    def upload_unpublished(self, image_url: str) -> str:
        return self._req("POST", f"{self.page}/photos", data={"url": image_url, "published": "false"})["id"]

    def multi_photo_post(self, media_ids: list[str], message: str) -> str:
        data = {"message": message, "attached_media": json.dumps([{"media_fbid": m} for m in media_ids])}
        return self._req("POST", f"{self.page}/feed", data=data)["id"]

    def permalink(self, post_id: str) -> Optional[str]:
        try:
            return self._req("GET", post_id, params={"fields": "permalink_url"}).get("permalink_url")
        except PublishError:
            return None
