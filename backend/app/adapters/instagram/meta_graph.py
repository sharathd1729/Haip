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
        """Fetch name + profile_pic for an Instagram user (requires instagram_manage_messages permission)."""
        return self._get(f"/{user_id}", params={"fields": "name,profile_pic"})

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
