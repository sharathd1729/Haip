"""Meta Marketing API, WRITE side (agency M5): click-to-message ads from approved content, pause, Conversions API.

Needs a token with `ads_management` (the read side needs only `ads_read`); a token without it gets Meta error 200/10,
surfaced as `bad_token`. Host pinned to graph.facebook.com; the token goes in the Authorization header.

Shape (developers.facebook.com/docs/marketing-api, read 21 Oct 2026; VERIFY on a live PAUSED ad before the first real
spend, Meta changes required fields between versions):
  campaign  objective OUTCOME_ENGAGEMENT, special_ad_categories [], spend_cap (paise), status PAUSED
  ad set    optimization_goal CONVERSATIONS, destination_type WHATSAPP | INSTAGRAM_DIRECT, promoted_object {page_id},
            daily_budget (paise), start/end time, custom-location targeting, status PAUSED
  creative  object_story_spec {page_id, instagram_user_id, link_data|video_data} with a message call to action
  ad        status PAUSED; everything is switched ACTIVE only after every object exists (never a half-built ad).
Money: the account must be in INR; amounts go to Meta in paise.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Optional

import httpx
import structlog

from app.adapters.marketing.meta_ads import GRAPH, MetaAdsError, _check_host

log = structlog.get_logger()

OBJECTIVE = "OUTCOME_ENGAGEMENT"
DESTINATION_TYPE = {"whatsapp": "WHATSAPP", "instagram": "INSTAGRAM_DIRECT"}
CALL_TO_ACTION = {
    "whatsapp": {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}},
    "instagram": {"type": "INSTAGRAM_MESSAGE", "value": {"app_destination": "INSTAGRAM_DIRECT"}},
}
MESSAGE_LINK = {"whatsapp": "https://api.whatsapp.com/send", "instagram": "https://www.instagram.com/"}


def paise(inr: int | float) -> int:
    return int(round(float(inr) * 100))


class MetaAdsWriter:
    def __init__(self, token: str, ad_account_id: str, client: Optional[httpx.Client] = None):
        if not token:
            raise MetaAdsError("No Meta access token is saved for this workspace.", status=401)
        self.token = token
        self.acct = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
        self.http = client or httpx.Client(timeout=60)

    def close(self) -> None:
        self.http.close()

    def _call(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        url = f"{GRAPH}/{path}"
        _check_host(url)
        form = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in (data or {}).items() if v is not None}
        try:
            resp = self.http.request(method, url, data=form if method != "GET" else None,
                                     params=form if method == "GET" else None,
                                     headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as exc:
            raise MetaAdsError(f"Could not reach Meta: {exc}", status=503) from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = (body or {}).get("error") or {}
            msg = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
            raise MetaAdsError(str(msg)[:300], status=resp.status_code, code=int(err.get("code") or 0))
        return body

    # ── Building blocks ─────────────────────────────────────────────────────────────────────────────────────────────

    def account_currency(self) -> str:
        return (self._call("GET", self.acct, {"fields": "currency"}).get("currency") or "").upper()

    def upload_image(self, jpeg: bytes) -> str:
        body = self._call("POST", f"{self.acct}/adimages", {"bytes": base64.b64encode(jpeg).decode()})
        images = body.get("images") or {}
        first = next(iter(images.values()), {})
        if not first.get("hash"):
            raise MetaAdsError("Meta did not return an image hash.")
        return first["hash"]

    def upload_video(self, video_url: str) -> str:
        return self._call("POST", f"{self.acct}/advideos", {"file_url": video_url})["id"]

    def create_campaign(self, name: str, *, spend_cap_inr: int) -> str:
        return self._call("POST", f"{self.acct}/campaigns", {
            "name": name[:200], "objective": OBJECTIVE, "status": "PAUSED", "special_ad_categories": [],
            "buying_type": "AUCTION", "spend_cap": paise(spend_cap_inr), "is_adset_budget_sharing_enabled": "false",
        })["id"]

    def create_adset(self, name: str, *, campaign_id: str, destination: str, page_id: str, daily_budget_inr: int,
                     starts: datetime, ends: datetime, audience: dict) -> str:
        targeting = {
            "geo_locations": {"custom_locations": [{"latitude": audience["latitude"], "longitude": audience["longitude"],
                                                    "radius": audience["radius_km"], "distance_unit": "kilometer"}]},
            "age_min": audience["age_min"], "age_max": audience["age_max"],
        }
        return self._call("POST", f"{self.acct}/adsets", {
            "name": name[:200], "campaign_id": campaign_id, "status": "PAUSED",
            "optimization_goal": "CONVERSATIONS", "billing_event": "IMPRESSIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "destination_type": DESTINATION_TYPE[destination], "promoted_object": {"page_id": page_id},
            "daily_budget": paise(daily_budget_inr), "start_time": starts.isoformat(), "end_time": ends.isoformat(),
            "targeting": targeting,
        })["id"]

    def create_creative(self, name: str, *, destination: str, page_id: str, instagram_user_id: Optional[str],
                        message: str, image_hash: Optional[str] = None, video_id: Optional[str] = None,
                        thumbnail_url: Optional[str] = None) -> str:
        cta = CALL_TO_ACTION[destination]
        if video_id:
            story = {"video_data": {"video_id": video_id, "image_url": thumbnail_url, "message": message,
                                    "call_to_action": cta}}
        else:
            story = {"link_data": {"image_hash": image_hash, "message": message, "link": MESSAGE_LINK[destination],
                                   "call_to_action": cta}}
        spec = {"page_id": page_id, **story}
        if instagram_user_id:
            spec["instagram_user_id"] = instagram_user_id
        return self._call("POST", f"{self.acct}/adcreatives", {"name": name[:200], "object_story_spec": spec})["id"]

    def create_ad(self, name: str, *, adset_id: str, creative_id: str) -> str:
        return self._call("POST", f"{self.acct}/ads", {"name": name[:200], "adset_id": adset_id,
                                                       "creative": {"creative_id": creative_id}, "status": "PAUSED"})["id"]

    def set_status(self, object_id: str, status: str) -> None:
        if status not in ("ACTIVE", "PAUSED"):
            raise ValueError("status must be ACTIVE or PAUSED")
        self._call("POST", object_id, {"status": status})

    # ── Conversions API ─────────────────────────────────────────────────────────────────────────────────────────────

    def send_events(self, dataset_id: str, events: list[dict], *, test_code: Optional[str] = None) -> dict:
        """POST /{dataset}/events. Returns {events_received, fbtrace_id}."""
        return self._call("POST", f"{dataset_id}/events", {"data": events, "test_event_code": test_code or None})
