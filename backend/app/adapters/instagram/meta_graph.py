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
# Instagram on the Meta Business (System User) connection: the same calls on Facebook's host, with the linked page's token.
FB_GRAPH_BASE = "https://graph.facebook.com/v20.0"


def base_for(access_token: str) -> str:
    """A Facebook token (EAA...) only works on graph.facebook.com, an Instagram Login token only on graph.instagram.com."""
    return FB_GRAPH_BASE if (access_token or "").startswith("EAA") else GRAPH_BASE


def subscribe_page(page_access_token: str, page_id: str) -> tuple[bool, str]:
    """Meta Business mode: switch on the linked Facebook page's subscription, without which Meta delivers no Instagram
    message webhooks for it. Returns (ok, error text); never raises."""
    try:
        resp = httpx.post(
            f"{FB_GRAPH_BASE}/{page_id}/subscribed_apps",
            data={"subscribed_fields": "messages,messaging_postbacks"},
            headers={"Authorization": f"Bearer {page_access_token}"},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__
    if resp.status_code == 200 and body.get("success") is True:
        return True, ""
    return False, str((body.get("error") or {}).get("message") or body or resp.status_code)[:200]

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


# Webhook fields HAIP handles (webhooks_instagram.py): DMs incl. echoes, button taps, ad referrals, comments.
WEBHOOK_FIELDS = "messages,messaging_postbacks,messaging_referral,comments,live_comments"


def subscribe_webhooks(access_token: str) -> tuple[bool, str]:
    """Subscribe the connected account to HAIP's webhook fields (Instagram API with Instagram Login).

    Without this call Meta sends no DMs for the account even though the token works. Returns (ok, error text);
    never raises, so a failed subscribe never undoes a successful connect.
    """
    ok, err = _subscribe(access_token, WEBHOOK_FIELDS)
    if not ok and "live_comments" in WEBHOOK_FIELDS:
        # Live comments are optional: if Meta refuses that field, still subscribe to the ones DMs need.
        ok, err = _subscribe(access_token, WEBHOOK_FIELDS.replace(",live_comments", ""))
    return ok, err


def _subscribe(access_token: str, fields: str) -> tuple[bool, str]:
    try:
        resp = httpx.post(
            f"{GRAPH_BASE}/me/subscribed_apps",
            data={"subscribed_fields": fields},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]
    if resp.status_code == 200 and body.get("success") is True:
        return True, ""
    return False, str((body.get("error") or {}).get("message") or body or resp.status_code)[:200]


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


def _meta_error(resp: httpx.Response) -> str:
    """Meta's own reason ("(#10) ...", code, subcode) from an error body, without anything secret."""
    try:
        err = (resp.json() or {}).get("error") or {}
    except ValueError:
        return resp.text[:200]
    parts = [str(err.get("message") or "").strip()]
    if err.get("code") is not None:
        parts.append(f"code {err.get('code')}" + (f"/{err.get('error_subcode')}" if err.get("error_subcode") else ""))
    return " ".join(p for p in parts if p) or resp.text[:200]


def _raise_for_status(resp: httpx.Response, method: str, path: str) -> None:
    """Like raise_for_status (callers still catch httpx.HTTPStatusError and read .response), but the message is
    Meta's reason and the path, never the full URL."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        reason = _meta_error(exc.response)
        logger.error("Instagram %s %s → %s %s", method, path, exc.response.status_code, reason)
        raise httpx.HTTPStatusError(
            f"Instagram {exc.response.status_code}: {reason}", request=exc.request, response=exc.response
        ) from None


class InstagramGraphAdapter:
    def __init__(self, access_token: str, ig_account_id: str):
        self._token = access_token
        self._account_id = ig_account_id
        self._base = base_for(access_token)
        # Messages hang off the Instagram account with an Instagram Login token, off the page ("me") with a page token.
        self._inbox = "me" if self._base == FB_GRAPH_BASE else ig_account_id

    # The token goes in the Authorization header, never the URL: httpx puts the URL in every error message, and those
    # messages end up in logs and in automation_runs (shown on screen). A leaked ?access_token= was seen there.
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base}/{path.lstrip('/')}"
        resp = httpx.post(url, json=payload, headers=self._headers(), timeout=15)
        _raise_for_status(resp, "POST", path)
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}/{path.lstrip('/')}"
        resp = httpx.get(url, params=params or {}, headers=self._headers(), timeout=15)
        _raise_for_status(resp, "GET", path)
        return resp.json()

    # ── Sending ────────────────────────────────────────────────────────────────

    def send_text(self, recipient_id: str, text: str) -> dict:
        """Send a plain-text DM to a user by their Instagram-scoped user ID."""
        result = self._post(f"/{self._inbox}/messages", {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        })
        return result  # {"message_id": "mid.xxx", "recipient_id": "..."}

    def send_quick_replies(self, recipient_id: str, text: str, quick_replies: list[dict]) -> dict:
        """Send a message with quick reply buttons."""
        return self._post(f"/{self._inbox}/messages", {
            "recipient": {"id": recipient_id},
            "message": {
                "text": text,
                "quick_replies": quick_replies,  # [{"content_type":"text","title":"Yes","payload":"YES"}]
            },
            "messaging_type": "RESPONSE",
        })

    def send_private_reply(self, comment_id: str, text: str, quick_replies: list[dict] | None = None) -> dict:
        """DM someone in response to their comment on our post or ad
        ("private reply"). A plain send_text to a person who has only
        commented is rejected by Meta as "outside of allowed window" -- the
        comment itself is what opens this one reply. Meta allows one private
        reply per comment, within 7 days of it. quick_replies: a tap on one opens the normal 24h window."""
        message: dict = {"text": text}
        if quick_replies:
            message["quick_replies"] = quick_replies
        return self._post(f"/{self._inbox}/messages", {
            "recipient": {"comment_id": comment_id},
            "message": message,
        })

    def send_link_button(self, recipient_id: str, text: str, button_title: str, url: str) -> dict:
        """A message with one link button (generic template; its title holds at most 80 characters, so a longer text goes
        first as its own message). Raises like _post; callers fall back to plain text + link."""
        title = text if len(text) <= 80 else button_title
        if len(text) > 80:
            self.send_text(recipient_id, text)
        return self._post(f"/{self._inbox}/messages", {
            "recipient": {"id": recipient_id},
            "message": {"attachment": {"type": "template", "payload": {
                "template_type": "generic",
                "elements": [{"title": title, "buttons": [{"type": "web_url", "url": url, "title": button_title}]}],
            }}},
            "messaging_type": "RESPONSE",
        })

    def follows_us(self, user_id: str) -> bool | None:
        """True/False when Meta says whether this person follows the account (is_user_follow_business), None when it
        will not say (Meta needs the person to have messaged us first; any error)."""
        try:
            data = self._get(f"/{user_id}", params={"fields": "is_user_follow_business"})
        except Exception:  # noqa: BLE001
            return None
        value = data.get("is_user_follow_business")
        return value if isinstance(value, bool) else None

    def reply_to_comment(self, comment_id: str, message: str) -> dict:
        """Post a public reply to a comment (T2.3 — comment-sourced quick replies)."""
        return self._post(f"/{comment_id}/replies", {"message": message})

    def mark_seen(self, sender_id: str) -> dict:
        """Send 'seen' receipt to a user."""
        return self._post(f"/{self._inbox}/messages", {
            "recipient": {"id": sender_id},
            "sender_action": "mark_seen",
        })

    def typing_on(self, sender_id: str) -> dict:
        return self._post(f"/{self._inbox}/messages", {
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
        """followers_count, follows_count (following), media_count, name, biography, username, website -- plain
        object fields, not the /insights sub-endpoint (username/website feed the profile score, phase 3)."""
        return self._get(f"/{self._account_id}", params={
            "fields": "followers_count,follows_count,media_count,name,biography,username,website",
        })

    def get_recent_media(self, limit: int = 12) -> list[dict]:
        data = self._get(f"/{self._account_id}/media", params={
            "fields": "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp,like_count,"
                      "comments_count",
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
