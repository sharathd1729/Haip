"""
Instagram Graph API adapter for sending DMs and managing conversations.

Uses the same Meta access token as WhatsApp (linked to the Instagram Business Account).
API version: v20.0
"""

from __future__ import annotations
import logging
from urllib.parse import urlparse
import httpx

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.instagram.com/v20.0"

# SSRF protection for inbound attachment media_url values (T0.2). Unlike
# Dograh's fixed hostnames, Meta's CDN serves media from many dynamically
# numbered subdomains (e.g. scontent-bom2-1.cdninstagram.com), so this is a
# domain-suffix allowlist rather than an exact-match set.
#
# NOTE: these are Meta's long-standing, documented CDN domains for
# Instagram/Messenger attachment delivery, but per the build plan this
# should be verified against a live webhook payload before being fully
# relied on for production media fetching -- flagged, not guessed blind.
_ALLOWED_MEDIA_HOST_SUFFIXES = (
    ".cdninstagram.com",
    "cdninstagram.com",
    ".fbcdn.net",
    "fbcdn.net",
    "lookaside.fbsbx.com",
)


def validate_media_url(url: str) -> bool:
    """
    Return True only for HTTPS URLs whose host is on Meta's CDN allowlist.
    Prevents SSRF via an attacker-controlled attachment payload URL.
    """
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_MEDIA_HOST_SUFFIXES)


class InstagramGraphAdapter:
    def __init__(self, access_token: str, ig_account_id: str):
        self._token = access_token
        self._account_id = ig_account_id

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        resp = httpx.post(
            url,
            json=payload,
            params={"access_token": self._token},
            timeout=15,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Instagram POST %s → %s %s", path, exc.response.status_code, exc.response.text[:300])
            raise
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        p = {"access_token": self._token, **(params or {})}
        resp = httpx.get(url, params=p, timeout=15)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Instagram GET %s → %s %s", path, exc.response.status_code, exc.response.text[:300])
            raise
        return resp.json()

    # ── Sending ────────────────────────────────────────────────────────────────

    def send_text(self, recipient_id: str, text: str) -> dict:
        """Send a plain-text DM to a user by their Instagram-scoped user ID."""
        result = self._post(f"/{self._account_id}/messages", {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        })
        return result  # {"message_id": "mid.xxx", "recipient_id": "..."}

    def send_quick_replies(self, recipient_id: str, text: str, quick_replies: list[dict]) -> dict:
        """Send a message with quick reply buttons."""
        return self._post(f"/{self._account_id}/messages", {
            "recipient": {"id": recipient_id},
            "message": {
                "text": text,
                "quick_replies": quick_replies,  # [{"content_type":"text","title":"Yes","payload":"YES"}]
            },
            "messaging_type": "RESPONSE",
        })

    def send_private_reply(self, comment_id: str, text: str) -> dict:
        """DM someone in response to their comment on our post or ad
        ("private reply"). A plain send_text to a person who has only
        commented is rejected by Meta as "outside of allowed window" -- the
        comment itself is what opens this one reply. Meta allows one private
        reply per comment, within 7 days of it."""
        return self._post(f"/{self._account_id}/messages", {
            "recipient": {"comment_id": comment_id},
            "message": {"text": text},
        })

    def reply_to_comment(self, comment_id: str, message: str) -> dict:
        """Post a public reply to a comment (T2.3 — comment-sourced quick replies)."""
        return self._post(f"/{comment_id}/replies", {"message": message})

    def mark_seen(self, sender_id: str) -> dict:
        """Send 'seen' receipt to a user."""
        return self._post(f"/{self._account_id}/messages", {
            "recipient": {"id": sender_id},
            "sender_action": "mark_seen",
        })

    def typing_on(self, sender_id: str) -> dict:
        return self._post(f"/{self._account_id}/messages", {
            "recipient": {"id": sender_id},
            "sender_action": "typing_on",
        })

    # ── Profile fetch ──────────────────────────────────────────────────────────

    def get_user_profile(self, user_id: str) -> dict:
        """Fetch name + username + profile_pic for an Instagram user (requires
        instagram_manage_messages permission). Meta's Send API user-profile
        endpoint no longer reliably returns "name" for most business
        integrations (platform restriction, not something we control) --
        "username" (the @handle) is still returned and is what callers should
        fall back to when "name" is empty."""
        return self._get(f"/{user_id}", params={"fields": "name,username,profile_pic"})

    # ── Conversation listing ───────────────────────────────────────────────────

    def get_conversations(self, limit: int = 20) -> list[dict]:
        """List recent IG DM conversations for the account."""
        data = self._get(
            f"/{self._account_id}/conversations",
            params={"platform": "instagram", "limit": limit, "fields": "id,participants,updated_time"},
        )
        return data.get("data", [])

    def get_messages_in_conversation(self, conversation_id: str, limit: int = 20) -> list[dict]:
        data = self._get(
            f"/{conversation_id}/messages",
            params={"fields": "id,message,from,created_time", "limit": limit},
        )
        return data.get("data", [])

    # ── Account insights ──────────────────────────────────────────────────────

    def get_account_insights(self, metrics: list[str], period: str = "day") -> list[dict]:
        """Organic account-level time-series insights (reach, follower_count,
        profile_views) -- requires instagram_manage_insights. Confirmed live:
        Meta silently omits a metric from the response instead of erroring
        the whole call when that metric isn't available for this
        account/period, so callers must not assume every requested metric
        comes back."""
        data = self._get(
            f"/{self._account_id}/insights",
            params={"metric": ",".join(metrics), "period": period},
        )
        return data.get("data", [])

    def get_account_engagement_totals(self, metrics: list[str]) -> dict[str, int]:
        """Confirmed live: engagement-style metrics (likes, comments, shares,
        saves, replies, accounts_engaged, total_interactions,
        profile_links_taps) return empty/omitted under the plain time-series
        call above -- they need metric_type=total_value instead. Returns
        {metric_name: value}, only for metrics Meta actually returned."""
        data = self._get(
            f"/{self._account_id}/insights",
            params={"metric": ",".join(metrics), "metric_type": "total_value", "period": "day"},
        )
        return {
            m["name"]: m.get("total_value", {}).get("value")
            for m in data.get("data", [])
            if m.get("total_value", {}).get("value") is not None
        }

    def get_follower_demographics(self, breakdown: str) -> list[dict]:
        """breakdown: one of city|country|age|gender. Confirmed live: needs
        Ratha's real follower count (5000+) comfortably clears whatever
        minimum-audience threshold Meta enforces before returning data --
        not independently confirmed what that minimum is, so a small/new
        account may get an empty result here, which is a real "not enough
        data yet" case, not a bug. Returns the raw
        [{"dimension_values": [...], "value": N}, ...] result list."""
        data = self._get(
            f"/{self._account_id}/insights",
            params={
                "metric": "follower_demographics", "metric_type": "total_value",
                "period": "lifetime", "breakdown": breakdown,
            },
        )
        try:
            return data["data"][0]["total_value"]["breakdowns"][0]["results"]
        except (KeyError, IndexError):
            return []

    def get_account_fields(self) -> dict:
        """followers_count, follows_count (following), media_count, name,
        biography -- plain object fields, not the /insights sub-endpoint."""
        return self._get(f"/{self._account_id}", params={
            "fields": "followers_count,follows_count,media_count,name,biography",
        })

    def get_recent_media(self, limit: int = 12) -> list[dict]:
        data = self._get(f"/{self._account_id}/media", params={
            "fields": "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,like_count,comments_count",
            "limit": limit,
        })
        return data.get("data", [])

    def list_media_page(self, limit: int = 25, after: str | None = None) -> tuple[list[dict], str | None]:
        """One page of the account's own posts and reels, newest first: (items, next cursor or None).

        Only the fields the knowledge base needs (id, caption, media_type, permalink, timestamp). Paging uses the `after` cursor
        against GRAPH_BASE, never the `paging.next` URL Meta returns, so the token is only ever sent to graph.instagram.com."""
        params = {"fields": "id,caption,media_type,permalink,timestamp", "limit": max(1, min(int(limit), 50))}
        if after:
            params["after"] = after
        data = self._get(f"/{self._account_id}/media", params=params)
        paging = data.get("paging") or {}
        cursor = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
        return data.get("data", []), cursor

    def get_media_insights(self, media_id: str, metrics: list[str]) -> dict[str, int]:
        """Per-post insights (reach, saved, shares, total_interactions).
        Confirmed live against a real recent post: reach=5115. NOT confirmed:
        whether a metric unsupported for a given media_type (e.g. a
        video-only metric requested against a photo) gets silently omitted
        (like account insights do) or raises for the whole call -- callers
        should catch httpx.HTTPStatusError per-post rather than assume
        either behavior, since this is called once per post in a loop and
        one bad metric/media_type combination must not abort the rest."""
        data = self._get(f"/{media_id}/insights", params={"metric": ",".join(metrics)})
        return {
            m["name"]: m["values"][0]["value"]
            for m in data.get("data", [])
            if m.get("values")
        }
