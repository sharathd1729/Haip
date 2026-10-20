"""Gemini image generation (generateContent with responseModalities=IMAGE), same GEMINI_API_KEY as the LLM routes.

Host pinned to generativelanguage.googleapis.com; the key goes in the x-goog-api-key header, never the URL. A real
request on 18 Oct 2026 (gemini-3.1-flash-image, 4:5) returned a JPEG in 15 s with usageMetadata reporting 1,120 image
tokens. Timeouts, 429 and 5xx are transient; a safety block or any other 4xx is not.
"""
import base64
import time

import httpx
import structlog

from app.adapters.image import ImageGenError, ImageModel, estimate_cost_usd
from app.core.config import settings

log = structlog.get_logger()

BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
_ALLOWED_HOST = "generativelanguage.googleapis.com"
TIMEOUT = 90
MAX_IMAGE_BYTES = 20 * 1024 * 1024
_OK_FINISH = {"STOP", "FINISH_REASON_UNSPECIFIED", None}


def generate(model: ImageModel, prompt: str, aspect_ratio: str, *, client: httpx.Client | None = None) -> tuple[bytes, dict]:
    if not settings.GEMINI_API_KEY:
        raise ImageGenError("GEMINI_API_KEY is not configured.", transient=False)
    url = f"{BASE}{model.path}:generateContent"
    if httpx.URL(url).host != _ALLOWED_HOST:
        raise ImageGenError("refusing to call an unexpected host", transient=False)
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}}}
    started = time.monotonic()
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        try:
            resp = c.post(url, json=body, headers={"x-goog-api-key": settings.GEMINI_API_KEY})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ImageGenError(f"Gemini image API did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if own:
            c.close()
    if resp.status_code != 200:
        transient = resp.status_code == 429 or resp.status_code >= 500
        raise ImageGenError(f"Gemini image API {resp.status_code}: {resp.text[:300]}", transient=transient)
    data = resp.json()
    feedback = (data.get("promptFeedback") or {}).get("blockReason")
    if feedback:
        raise ImageGenError(f"Gemini refused the description ({feedback}). Try wording it differently.", transient=False)
    cands = data.get("candidates") or []
    if not cands:
        raise ImageGenError("Gemini returned no image.", transient=False)
    reason = cands[0].get("finishReason")
    raw, mime = None, None
    for part in (cands[0].get("content") or {}).get("parts") or []:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            raw, mime = base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type")
            break
    if raw is None:
        why = f" ({reason})" if reason not in _OK_FINISH else ""
        raise ImageGenError(f"Gemini did not return an image{why}. Try wording it differently.", transient=False)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageGenError("Generated image is unexpectedly large.", transient=False)
    usage = data.get("usageMetadata") or {}
    image_tokens = sum(d.get("tokenCount", 0) for d in usage.get("candidatesTokensDetails") or [] if d.get("modality") == "IMAGE")
    output_tokens = usage.get("candidatesTokenCount") or image_tokens
    input_tokens = usage.get("promptTokenCount") or 0
    text_tokens = max(output_tokens - image_tokens, 0) + (usage.get("thoughtsTokenCount") or 0)
    secs = round(time.monotonic() - started, 1)
    log.info("gemini_image_generated", model=model.key, secs=secs, bytes=len(raw), image_tokens=image_tokens)
    return raw, {"provider": "gemini", "model": model.key, "aspect_ratio": aspect_ratio, "mime_type": mime,
                 "finish_reason": reason, "secs": secs, "input_tokens": input_tokens, "image_tokens": image_tokens,
                 "text_tokens": text_tokens,
                 "est_cost_usd": estimate_cost_usd(model, input_tokens, image_tokens, text_tokens)}
