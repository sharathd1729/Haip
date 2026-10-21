"""AI video adapters (agency M2b): turn a few of the workspace's own approved photos into a short vertical clip.

Higgsfield (docs.higgsfield.ai, read 21 Oct 2026): one queue API for every model.
  * Submit: POST https://api.higgsfield.ai/{model path} with JSON; header `Authorization: Key {key_id}:{key_secret}`
    (server side only) and an `Idempotency-Key` so a retried submit never pays twice. Answer: request_id, status_url.
  * Status: GET /requests/{request_id}/status -> queued | in_progress | completed | failed | nsfw | canceled; a
    completed video is at `video.url`. Outputs are kept "at least seven days"; HAIP copies the file at once.
  * Webhooks exist (`hf_webhook`) but deliveries are not signed, so HAIP only polls the authenticated status URL.
Models are listed with their request shape; a model is usable only when `enabled` (path + fields confirmed in the docs).
Each workspace brings its own Higgsfield key (Integration kind "higgsfield", encrypted), so usage bills to them.
"""
from dataclasses import dataclass
from typing import Optional

import httpx

API = "https://api.higgsfield.ai"
TIMEOUT = 30
MAX_VIDEO_BYTES = 100 * 1024 * 1024
TERMINAL = {"completed", "failed", "nsfw", "canceled"}


@dataclass(frozen=True)
class VideoModel:
    key: str
    label: str
    path: str
    enabled: bool
    max_images: int
    durations: tuple[int, ...]
    blocked_reason: Optional[str] = None


DEFAULT_MODEL = "seedance-2.5-reference"

MODELS: dict[str, VideoModel] = {
    # docs.higgsfield.ai/docs/models/seedance-2-5/reference-to-video: image_urls (1-30), prompt, duration 4-30 s,
    # resolution 480p/720p/1080p, aspect_ratio incl. 9:16, generate_audio (default true); output video.url.
    "seedance-2.5-reference": VideoModel(key="seedance-2.5-reference", label="Seedance 2.5 (photos to video)",
                                         path="bytedance/seedance-2.5/reference-to-video", enabled=True,
                                         max_images=6, durations=(5, 8, 10)),
}


class VideoError(Exception):
    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


def get_model(key: Optional[str]) -> VideoModel:
    model = MODELS.get(key or DEFAULT_MODEL)
    if model is None or not model.enabled:
        raise VideoError((model.blocked_reason if model else None) or f"Unknown video model: {key}", transient=False)
    return model


def catalogue() -> list[dict]:
    return [{"key": m.key, "label": m.label, "enabled": m.enabled, "durations": list(m.durations),
             "max_images": m.max_images, "default": m.key == DEFAULT_MODEL} for m in MODELS.values()]


class Higgsfield:
    def __init__(self, key_id: str, key_secret: str, client: Optional[httpx.Client] = None):
        if not key_id or not key_secret:
            raise VideoError("Higgsfield is not connected for this workspace.", transient=False)
        self._h = {"Authorization": f"Key {key_id}:{key_secret}"}
        self._c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        self._own = client is None

    def close(self) -> None:
        if self._own:
            self._c.close()

    def _call(self, method: str, path: str, **kw) -> dict:
        url = f"{API}{path}"
        if httpx.URL(url).host != "api.higgsfield.ai":
            raise VideoError("refusing to call an unexpected host", transient=False)
        try:
            r = self._c.request(method, url, headers={**self._h, **kw.pop("headers", {})}, **kw)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise VideoError(f"Higgsfield did not answer: {type(exc).__name__}", transient=True) from exc
        if r.status_code >= 400:
            raise VideoError(f"Higgsfield {r.status_code}: {r.text[:200]}",
                             transient=r.status_code == 429 or r.status_code >= 500)
        return r.json() if r.content else {}

    def submit(self, model: VideoModel, image_urls: list[str], prompt: str, duration: int, idempotency_key: str) -> str:
        if not 1 <= len(image_urls) <= model.max_images or duration not in model.durations:
            raise VideoError("Pick 1-%d photos and one of the offered lengths." % model.max_images, transient=False)
        body = {"image_urls": image_urls, "prompt": prompt[:1000], "duration": duration, "resolution": "720p",
                "aspect_ratio": "9:16", "generate_audio": False}       # no audio: licensed music can't be posted via the API
        data = self._call("POST", f"/{model.path}", json=body,
                          headers={"Content-Type": "application/json", "Idempotency-Key": idempotency_key})
        if not data.get("request_id"):
            raise VideoError("Higgsfield returned no request id.", transient=False)
        return data["request_id"]

    def status(self, request_id: str) -> dict:
        """{status, video_url?, error?}"""
        data = self._call("GET", f"/requests/{request_id}/status")
        return {"status": data.get("status"), "video_url": (data.get("video") or {}).get("url"),
                "error": data.get("error")}

    def download(self, url: str) -> bytes:
        from app.core.url_safety import UnsafeURLError, assert_public_url
        try:
            assert_public_url(url, allow_http=False)       # https, and every address of the host is public (SSRF)
        except UnsafeURLError as exc:
            raise VideoError(f"refusing to download: {exc}", transient=False) from exc
        try:
            with self._c.stream("GET", url) as r:
                if r.status_code != 200:
                    raise VideoError(f"Download failed ({r.status_code})", transient=r.status_code >= 500)
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        raise VideoError("The video is larger than 100 MB.", transient=False)
                    chunks.append(chunk)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise VideoError(f"Download failed: {type(exc).__name__}", transient=True) from exc
        return b"".join(chunks)
