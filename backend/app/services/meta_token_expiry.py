"""Warn before a Meta access token expires, instead of after it has broken sending.

Ratha's WhatsApp System User token was saved as "permanent" in the setup text, but Meta reports it
expiring on 24 Nov 2026. Meta's own debug_token endpoint says when, so we ask it daily, remember the
answer on the integration, and email the owners at 30, 14, 7, 3 and 1 days.

Pure helpers live here so the Celery task stays thin and the thresholds can be tested without a network.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()

GRAPH = "https://graph.facebook.com/v20.0"

# Alert once when the days left first drop to each of these.
THRESHOLDS = (30, 14, 7, 3, 1)
# The Dashboard bar and Integrations page turn amber from here.
WARN_WITHIN_DAYS = 14


def days_left(expires_at: int, now: Optional[float] = None) -> int:
    """Whole days until `expires_at` (unix seconds). Zero or negative once it has passed."""
    return int((expires_at - (now if now is not None else time.time())) // 86400)


def bucket(days: int) -> Optional[int]:
    """The alert threshold this many days left falls into, or None when it is comfortably far away.

    0 means already expired. The smallest threshold that is still >= days wins: 20 days left is the "30"
    bucket, 5 days left is the "7" bucket."""
    if days <= 0:
        return 0
    for t in sorted(THRESHOLDS):
        if days <= t:
            return t
    return None


def iso(expires_at: int) -> str:
    return datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def days_until_iso(value: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    dt = parse_iso(value)
    if dt is None:
        return None
    return int((dt - (now or datetime.now(timezone.utc))).total_seconds() // 86400)


def fetch_expiry(token: str) -> Optional[dict]:
    """Ask Meta when this token expires. Returns {"valid": bool, "expires_at": int} (expires_at 0 means
    it never expires), or None when Meta could not be reached or the token is not a Facebook Graph token.
    A network failure is not evidence about the token, so callers skip rather than alert."""
    try:
        resp = httpx.get(
            f"{GRAPH}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=15,
        )
        data = (resp.json() or {}).get("data")
    except Exception as exc:  # network, bad JSON
        log.warning("meta_token_expiry_probe_failed", error=str(exc))
        return None
    if not isinstance(data, dict) or "is_valid" not in data:
        return None
    return {"valid": bool(data.get("is_valid")), "expires_at": int(data.get("expires_at") or 0)}
