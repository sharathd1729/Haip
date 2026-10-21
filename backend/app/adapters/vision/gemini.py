"""Gemini vision: one photo + an instruction in, a JSON object out (generateContent, responseMimeType JSON).

Same host pinning and header-only key as adapters/image/gemini.py. Timeouts, 429 and 5xx are transient; a safety
block, unparseable JSON or any other 4xx is not.
"""
import base64
import json
import time

import httpx
import structlog

from app.adapters.vision import VisionError, VisionModel
from app.core.config import settings

log = structlog.get_logger()

BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
_ALLOWED_HOST = "generativelanguage.googleapis.com"
TIMEOUT = 45


def describe(model: VisionModel, jpeg: bytes, prompt: str, *, client: httpx.Client | None = None) -> tuple[dict, dict]:
    if not settings.GEMINI_API_KEY:
        raise VisionError("GEMINI_API_KEY is not configured.", transient=False)
    url = f"{BASE}{model.path}:generateContent"
    if httpx.URL(url).host != _ALLOWED_HOST:
        raise VisionError("refusing to call an unexpected host", transient=False)
    body = {"contents": [{"parts": [{"text": prompt},
                                    {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    started = time.monotonic()
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        try:
            resp = c.post(url, json=body, headers={"x-goog-api-key": settings.GEMINI_API_KEY})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise VisionError(f"Gemini did not answer: {type(exc).__name__}", transient=True) from exc
    finally:
        if own:
            c.close()
    if resp.status_code != 200:
        raise VisionError(f"Gemini {resp.status_code}: {resp.text[:300]}",
                          transient=resp.status_code == 429 or resp.status_code >= 500)
    data = resp.json()
    if (data.get("promptFeedback") or {}).get("blockReason"):
        raise VisionError("Gemini refused to look at this photo.", transient=False)
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts).strip()
    try:
        answer = json.loads(text.removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError as exc:
        raise VisionError("Gemini's answer was not valid JSON.", transient=False) from exc
    if not isinstance(answer, dict):
        raise VisionError("Gemini's answer was not a JSON object.", transient=False)
    usage = data.get("usageMetadata") or {}
    tokens_in, tokens_out = usage.get("promptTokenCount") or 0, usage.get("candidatesTokenCount") or 0
    secs = round(time.monotonic() - started, 1)
    log.info("gemini_vision_described", model=model.key, secs=secs, tokens_in=tokens_in)
    return answer, {"provider": "gemini", "model": model.key, "secs": secs, "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "est_cost_usd": round((tokens_in * model.price_in + tokens_out * model.price_out) / 1_000_000, 6)}
