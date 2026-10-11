"""One health model for integrations.

The Integrations page, the Dashboard status bar and the D3 insight used to each decide "is this
healthy?" differently. The bar compared ``status == "connected"`` (the stored value is ``"active"``),
so every working integration fell through to "unknown" and the bar showed a problem all the time,
while the Integrations page, which reads ``status`` directly, said Connected.

Rule, in one place:
  * ``error``                      -> red    (a check failed or the token was rejected)
  * ``active``                     -> green  (receiving/sending works)
  * ``active`` + polled PMS sync with no successful sync for a while -> yellow / red
  * ``pending`` / ``disconnected`` -> off    (owner has not connected it or turned it off: not a fault)

Webhook-driven channels (WhatsApp, Instagram, IVR) have no regular poll, so an old ``last_health_at``
says nothing about them and never degrades them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

GREEN, YELLOW, RED, OFF = "green", "yellow", "red", "off"

# Integrations whose health comes from a scheduled sync that stamps last_health_at.
POLLED_KINDS = frozenset({"hostaway", "retalwise"})
POLLED_YELLOW_AFTER = timedelta(hours=3)   # the sync runs hourly
POLLED_RED_AFTER = timedelta(hours=12)

LABELS = {
    "whatsapp_meta": "WhatsApp", "whatsapp": "WhatsApp", "instagram": "Instagram",
    "callerdesk": "IVR", "acefone": "IVR (Acefone)", "mcube": "IVR (Mcube)", "vobiz": "IVR (Vobiz)",
    "hostaway": "Hostaway", "retalwise": "RentalWise", "meta_ads": "Meta Ads",
}


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def token_days_left(config: Optional[dict], now: Optional[datetime] = None) -> Optional[int]:
    """Days until the saved Meta token ends (set by the daily expiry check), or None when it never
    expires or has not been checked."""
    from app.services.meta_token_expiry import days_until_iso
    return days_until_iso((config or {}).get("token_expires_at"), now)


def classify(
    kind: str, status: str, last_health_at: Optional[str], now: Optional[datetime] = None,
    config: Optional[dict] = None,
) -> str:
    if status == "error":
        return RED
    if status != "active":
        return OFF
    # A token that is about to end is a fault in waiting: amber inside two weeks, red once it has ended.
    left = token_days_left(config, now)
    if left is not None:
        from app.services.meta_token_expiry import WARN_WITHIN_DAYS
        if left <= 0:
            return RED
        if left <= WARN_WITHIN_DAYS:
            return YELLOW
    if kind in POLLED_KINDS:
        last = _parse(last_health_at)
        if last is None:
            return YELLOW
        age = (now or datetime.now(timezone.utc)) - last
        if age > POLLED_RED_AFTER:
            return RED
        if age > POLLED_YELLOW_AFTER:
            return YELLOW
    return GREEN


def label(kind: str) -> str:
    return LABELS.get(kind, kind.replace("_", " ").title())
