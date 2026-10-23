"""Meta Marketing API (read only): which ad accounts a token can see, and daily ad-level insights.

Needs a token with `ads_read` (a System User token whose ad account is assigned to it works without App
Review for your own business assets). The host is pinned to graph.facebook.com, including for the
`paging.next` URLs Meta returns, so a poisoned response cannot make us fetch from anywhere else.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator, Optional
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger()

GRAPH_HOST = "graph.facebook.com"
GRAPH = f"https://{GRAPH_HOST}/v20.0"

# Meta throttles by error code, not only HTTP status: 4 app, 17 user, 32 page, 613 custom, 80004 ads insights.
RATE_LIMIT_CODES = {4, 17, 32, 613, 80004}
# Click-to-WhatsApp / Messenger / Instagram ads report "conversations started" under these action types.
CONVERSATION_ACTIONS = ("onsite_conversion.messaging_conversation_started_7d", "onsite_conversion.messaging_conversation_started")
LEAD_ACTIONS = ("lead", "onsite_conversion.lead_grouped")
FIRST_REPLY_ACTIONS = ("onsite_conversion.messaging_first_reply",)

INSIGHT_FIELDS = ",".join([
    "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name",
    "spend", "impressions", "reach", "clicks", "unique_clicks", "inline_link_clicks", "frequency", "ctr", "cpm", "cpc",
    "actions", "account_currency", "date_start",
    # Watch curve (studio plan phase 1): hook rate = 3-second views / impressions, hold rate = ThruPlays / 3-second views.
    "inline_link_click_ctr", "video_thruplay_watched_actions", "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p95_watched_actions", "video_p100_watched_actions", "video_avg_time_watched_actions",
])
# insights field -> ad_metrics column. Each is a list of {action_type: video_view, value}.
VIDEO_FIELDS = {"video_thruplay_watched_actions": "video_thruplays", "video_p25_watched_actions": "video_p25",
                "video_p50_watched_actions": "video_p50", "video_p75_watched_actions": "video_p75",
                "video_p95_watched_actions": "video_p95", "video_p100_watched_actions": "video_p100"}

ENTITY_FIELDS = {
    "campaign": "id,name,objective,status,effective_status,daily_budget,lifetime_budget,start_time,stop_time",
    "adset": ("id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,"
              "start_time,end_time,targeting"),
    "ad": ("id,name,campaign_id,adset_id,status,effective_status,"
           "creative{id,name,title,body,thumbnail_url,image_url,object_type,call_to_action_type}"),
}
ENTITY_EDGE = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}


class MetaAdsError(Exception):
    def __init__(self, message: str, *, status: int = 0, code: int = 0):
        super().__init__(message)
        self.status, self.code = status, code

    @property
    def rate_limited(self) -> bool:
        return self.status == 429 or self.code in RATE_LIMIT_CODES

    @property
    def bad_token(self) -> bool:
        return self.status in (401, 403) or self.code in (190, 102, 10, 200)


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != GRAPH_HOST:
        raise MetaAdsError(f"Refusing to follow a non-Graph URL: {parsed.hostname}")


def _get(url: str, params: Optional[dict] = None) -> dict:
    _check_host(url)
    try:
        resp = httpx.get(url, params=params, timeout=30)
    except httpx.HTTPError as exc:
        raise MetaAdsError(f"Could not reach Meta: {exc}") from exc
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error") or {}
        raise MetaAdsError(str(err.get("message") or f"HTTP {resp.status_code}")[:300],
                           status=resp.status_code, code=int(err.get("code") or 0))
    return body


def list_ad_accounts(token: str) -> list[dict]:
    """Ad accounts this token can read: [{id: "act_123", name, currency, status}]."""
    out: list[dict] = []
    body = _get(f"{GRAPH}/me/adaccounts", {
        "access_token": token, "fields": "account_id,name,currency,account_status", "limit": 50,
    })
    for a in body.get("data", []):
        out.append({"id": a.get("id") or f"act_{a.get('account_id')}", "name": a.get("name") or "", "currency": a.get("currency") or "INR",
                    "status": a.get("account_status")})
    return out


def _num(v, default=Decimal("0")) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return default


def _action_total(actions, names) -> int:
    for a in actions or []:
        if a.get("action_type") in names:
            try:
                return int(float(a.get("value", 0)))
            except (TypeError, ValueError):
                return 0
    return 0


def _first_value(actions):
    """The value of a one-entry action list (average watch time), or None."""
    for a in actions or []:
        if isinstance(a, dict):
            return a.get("value")
    return None


def parse_row(raw: dict) -> Optional[dict]:
    """One insights row, normalised. None when it has no ad or no date (nothing to key it on)."""
    ad_id, day = raw.get("ad_id"), raw.get("date_start")
    if not ad_id or not day:
        return None
    return {
        "date": date.fromisoformat(day),
        "campaign_id": raw.get("campaign_id") or "", "campaign_name": raw.get("campaign_name") or "",
        "adset_id": raw.get("adset_id") or "", "adset_name": raw.get("adset_name") or "",
        "ad_id": ad_id, "ad_name": raw.get("ad_name") or "",
        "spend": _num(raw.get("spend")), "impressions": int(_num(raw.get("impressions"))),
        "reach": int(_num(raw.get("reach"))), "clicks": int(_num(raw.get("clicks"))),
        "frequency": _num(raw.get("frequency")), "ctr": _num(raw.get("ctr")), "cpm": _num(raw.get("cpm")),
        "conversations_started": _action_total(raw.get("actions"), CONVERSATION_ACTIONS),
        "leads": _action_total(raw.get("actions"), LEAD_ACTIONS),
        "currency": raw.get("account_currency") or "INR",
        "link_clicks": int(_num(raw.get("inline_link_clicks"))) or _action_total(raw.get("actions"), ("link_click",)),
        "unique_clicks": int(_num(raw.get("unique_clicks"))),
        "post_engagement": _action_total(raw.get("actions"), ("post_engagement",)),
        "video_views": _action_total(raw.get("actions"), ("video_view",)),
        "first_replies": _action_total(raw.get("actions"), FIRST_REPLY_ACTIONS),
        "cpc": _num(raw.get("cpc")),
        "link_ctr": _num(raw.get("inline_link_click_ctr")),
        "video_avg_watch_s": _num(_first_value(raw.get("video_avg_time_watched_actions"))),
        **{col: _action_total(raw.get(f), ("video_view",)) for f, col in VIDEO_FIELDS.items()},
        "actions": [a for a in (raw.get("actions") or []) if isinstance(a, dict)][:60] or None,
    }


def fetch_insights(token: str, ad_account_id: str, since: date, until: date, *, max_pages: int = 40) -> Iterator[dict]:
    """Daily ad-level insights for [since, until], following Meta's pagination."""
    acct = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
    body = _get(f"{GRAPH}/{acct}/insights", {
        "access_token": token, "level": "ad", "time_increment": 1, "fields": INSIGHT_FIELDS, "limit": 500,
        "time_range": f'{{"since":"{since.isoformat()}","until":"{until.isoformat()}"}}',
    })
    pages = 0
    while True:
        for raw in body.get("data", []):
            row = parse_row(raw)
            if row:
                yield row
        nxt = (body.get("paging") or {}).get("next")
        pages += 1
        if not nxt or pages >= max_pages:
            break
        body = _get(nxt)


# ── details: campaigns, ad sets, ads ──────────────────────────────────────────

def _minor(v) -> Optional[Decimal]:
    """Meta reports budgets in the currency's smallest unit (paise for INR)."""
    if v in (None, ""):
        return None
    try:
        return (Decimal(str(v)) / 100).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _when(v) -> Optional[datetime]:
    if not v:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def _creative(c) -> Optional[dict]:
    if not isinstance(c, dict):
        return None
    keep = {k: c.get(k) for k in ("name", "title", "body", "thumbnail_url", "image_url", "object_type", "call_to_action_type") if c.get(k)}
    return keep or None


def parse_entity(level: str, raw: dict) -> Optional[dict]:
    if not raw.get("id"):
        return None
    return {
        "level": level, "entity_id": raw["id"], "name": raw.get("name") or "",
        "campaign_id": raw.get("campaign_id") or (raw["id"] if level == "campaign" else ""),
        "adset_id": raw.get("adset_id") or (raw["id"] if level == "adset" else ""),
        "status": raw.get("status"), "effective_status": raw.get("effective_status"),
        "objective": raw.get("objective"), "optimization_goal": raw.get("optimization_goal"),
        "daily_budget": _minor(raw.get("daily_budget")), "lifetime_budget": _minor(raw.get("lifetime_budget")),
        "starts_at": _when(raw.get("start_time")), "ends_at": _when(raw.get("stop_time") or raw.get("end_time")),
        "creative": _creative(raw.get("creative")) if level == "ad" else None,
        "targeting": raw.get("targeting") if level == "adset" and isinstance(raw.get("targeting"), dict) else None,
    }


def fetch_entities(token: str, ad_account_id: str, *, max_pages: int = 30) -> Iterator[dict]:
    """Every campaign, ad set and ad in the account, with its status, budget, creative and audience."""
    acct = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
    for level in ("campaign", "adset", "ad"):
        body = _get(f"{GRAPH}/{acct}/{ENTITY_EDGE[level]}", {
            "access_token": token, "fields": ENTITY_FIELDS[level], "limit": 200,
        })
        pages = 0
        while True:
            for raw in body.get("data", []):
                row = parse_entity(level, raw)
                if row:
                    yield row
            nxt = (body.get("paging") or {}).get("next")
            pages += 1
            if not nxt or pages >= max_pages:
                break
            body = _get(nxt)


def summarize_targeting(t: Optional[dict]) -> Optional[dict]:
    """Who an ad set is shown to, in words: ages, genders, places, interests, platforms."""
    if not isinstance(t, dict):
        return None
    geo = t.get("geo_locations") or {}
    places = [*geo.get("countries", []), *[c.get("name") for c in geo.get("cities", []) if c.get("name")],
              *[r.get("name") for r in geo.get("regions", []) if r.get("name")]]
    interests = [i.get("name") for g in (t.get("flexible_spec") or []) for i in g.get("interests", []) if i.get("name")]
    genders = {1: "Men", 2: "Women"}
    # Meta caps age at 65, shown as "65+"; any lower upper bound is a real limit.
    age_max = t.get("age_max", 65)
    ages = f"{t.get('age_min', 18)} to {age_max}{'+' if age_max >= 65 else ''}"
    return {
        "ages": ages if (t.get("age_min") or t.get("age_max")) else None,
        "genders": [genders[g] for g in t.get("genders", []) if g in genders] or ["All"],
        "places": places[:8],
        "interests": interests[:8],
        "platforms": [*t.get("publisher_platforms", [])],
    }
