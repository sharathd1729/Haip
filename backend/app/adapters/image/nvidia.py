"""NVIDIA hosted image generation (ai.api.nvidia.com/v1/genai/...), same NVIDIA_API_KEY as the LLM routes.

Hosts are pinned (no other host is ever called with the key). The service may answer 202 with an NVCF-REQID while the
job queues; that is polled on api.nvcf.nvidia.com until done or the time budget runs out. Live behaviour on 18 Oct 2026:
two real FLUX.1-schnell requests did not answer within 300 s, so callers must treat timeouts as transient and the
Celery task bounds the retries.
"""
import base64
import time
from typing import Optional

import httpx
import structlog

from app.adapters.image import ImageGenError, ImageModel
from app.core.config import settings

log = structlog.get_logger()

GENAI_BASE = "https://ai.api.nvidia.com/v1/genai/"
STATUS_BASE = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/"
_ALLOWED_HOSTS = {"ai.api.nvidia.com", "api.nvcf.nvidia.com"}
REQUEST_TIMEOUT = 180          # seconds for one HTTP call
TOTAL_BUDGET = 300             # seconds including polling
POLL_EVERY = 5
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _check_host(url: str) -> None:
    host = httpx.URL(url).host
    if host not in _ALLOWED_HOSTS:
        raise ImageGenError(f"refusing to call unexpected host {host}", transient=False)


def _classify(resp: httpx.Response) -> ImageGenError:
    transient = resp.status_code == 429 or resp.status_code >= 500
    return ImageGenError(f"NVIDIA image API {resp.status_code}: {resp.text[:300]}", transient=transient)


def _image_from(data: dict) -> tuple[bytes, dict]:
    arts = data.get("artifacts") or data.get("data") or []
    if not arts:
        raise ImageGenError("NVIDIA returned no image.", transient=False)
    art = arts[0]
    reason = art.get("finishReason") or art.get("finish_reason")
    if reason and reason not in ("SUCCESS", "success", "stop"):
        raise ImageGenError(f"NVIDIA did not finish the image ({reason}).", transient=False)
    b64 = art.get("base64") or art.get("b64_json")
    if not b64:
        raise ImageGenError("NVIDIA response had no image data.", transient=False)
    raw = base64.b64decode(b64)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageGenError("Generated image is unexpectedly large.", transient=False)
    return raw, {"seed": art.get("seed"), "finish_reason": reason}


def generate(model: ImageModel, prompt: str, width: int, height: int, *, seed: Optional[int] = None,
             client: Optional[httpx.Client] = None) -> tuple[bytes, dict]:
    if not settings.NVIDIA_API_KEY:
        raise ImageGenError("NVIDIA_API_KEY is not configured.", transient=False)
    url = GENAI_BASE + model.path
    _check_host(url)
    headers = {"Authorization": f"Bearer {settings.NVIDIA_API_KEY}", "Accept": "application/json"}
    body: dict = {"prompt": prompt, "width": width, "height": height}
    if model.steps:
        body["steps"] = model.steps
    if seed is not None:
        body["seed"] = seed
    started = time.monotonic()
    own = client is None
    c = client or httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=False)
    try:
        try:
            resp = c.post(url, json=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ImageGenError(f"NVIDIA image API did not answer: {type(exc).__name__}", transient=True) from exc
        while resp.status_code == 202:
            req_id = resp.headers.get("NVCF-REQID") or resp.headers.get("nvcf-reqid")
            if not req_id or time.monotonic() - started > TOTAL_BUDGET:
                raise ImageGenError("NVIDIA image job still queued after the time budget.", transient=True)
            time.sleep(POLL_EVERY)
            status_url = STATUS_BASE + req_id
            _check_host(status_url)
            try:
                resp = c.get(status_url, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise ImageGenError(f"NVIDIA status poll failed: {type(exc).__name__}", transient=True) from exc
        if resp.status_code != 200:
            raise _classify(resp)
        raw, meta = _image_from(resp.json())
    finally:
        if own:
            c.close()
    log.info("nvidia_image_generated", model=model.key, secs=round(time.monotonic() - started, 1), bytes=len(raw))
    return raw, {"provider": "nvidia", "model": model.key, "width": width, "height": height, **meta}
