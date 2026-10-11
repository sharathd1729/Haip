"""Meta Marketing API (read only): which ad accounts a token can see, and daily ad-level insights.

Needs a token with `ads_read` (a System User token whose ad account is assigned to it works without App
Review for your own business assets). The host is pinned to graph.facebook.com, including for the
`paging.next` URLs Meta returns, so a poisoned response cannot make us fetch from anywhere else.
"""
from __future__ import annotations

from datetime import date
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

INSIGHT_FIELDS = ",".join([
    "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name",
    "spend", "impressions", "reach", "clicks", "frequency", "ctr", "cpm",
    "actions", "account_currency", "date_start",
])


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
