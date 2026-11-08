"""One health model for integrations.

The Integrations page, the Dashboard status bar and the D3 insight used to each decide "is this
healthy?" differently. The bar compared ``status == "connected"`` (the stored value is ``"active"``),
so every working integration fell through to "unknown" and the bar showed a problem all the time,
while the Integrations page, which reads ``status`` directly, said Connected.

Rule, in one place:
  * ``error``                      -> red    (a check failed or the token was rejected)
  * ``active``                     -> green  (receiving/sending works)
  * ``active`` + polled PMS sync with no successful sync for a while -> yellow / red
  * ``active`` + Google pull (Business Profile metrics, Search Console) failing -> yellow after one failure, red after
    three in a row (``config["metrics_pull"]``, written by google_surfaces_sync)
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
# Integrations whose scheduled Google pull records failures in config["metrics_pull"] (google_surfaces_sync).
PULL_KINDS = frozenset({"google_business", "search_console"})
PULL_RED_FAILURES = 3

LABELS = {
    "whatsapp_meta": "WhatsApp", "whatsapp": "WhatsApp", "instagram": "Instagram",
    "callerdesk": "IVR", "acefone": "IVR (Acefone)", "mcube": "IVR (Mcube)", "vobiz": "IVR (Vobiz)",
    "hostaway": "Hostaway", "retalwise": "RentalWise", "meta_ads": "Meta Ads",
    "google_business": "Google Business Profile", "search_console": "Google Search Console",
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
    if kind in PULL_KINDS:
        failures = pull_failure(config)[0]
        if failures >= PULL_RED_FAILURES:
            return RED
        if failures:
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


def pull_failure(config: Optional[dict]) -> tuple[int, Optional[str]]:
    """(failures in a row, the plain-words reason) of a Google pull; (0, None) when it last worked."""
    st = (config or {}).get("metrics_pull") or {}
    return int(st.get("failures") or 0), st.get("last_error")


def label(kind: str) -> str:
    return LABELS.get(kind, kind.replace("_", " ").title())


# ── IVR silence ─────────────────────────────────────────────────────────────────────────────────────────────────
# A webhook channel never ages above, so a dead IVR stays green. Real case, Ratha: no call reached HAIP for 43-69 hours
# on 6 Oct and 27-30 Oct 2026 (the Vobiz wallet had gone negative) while WhatsApp / Instagram leads kept coming. This rule
# says the IVR is silent when, during business hours, the gap since its last call is far longer than this business's own
# normal gap AND people kept writing in that gap. Calls are counted by ``created_at`` (Vobiz calls had an empty
# ``started_at`` until scripts/backfill_call_timestamps.py ran).
BUSINESS_HOURS = (9, 21)          # local hours a call is expected in (IST)
IVR_BASELINE_DAYS = 28
IVR_MIN_BASELINE_CALLS = 20       # fewer calls in 28 days = no normal rate to compare with: never flagged
IVR_MIN_SILENT_HOURS = 4
IVR_GAP_FACTOR = 3                # silent for 3x the normal business-hours gap between calls
IVR_MIN_MESSAGES = 3              # inbound WhatsApp / Instagram messages in the silent stretch


def _business_hours_between(start: datetime, end: datetime) -> float:
    from app.services.date_presets import IST

    lo, hi = BUSINESS_HOURS
    total, cur = 0.0, start.astimezone(IST)
    end = end.astimezone(IST)
    while cur < end:
        nxt = min(end, (cur + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
        if lo <= cur.hour < hi:
            total += (nxt - cur).total_seconds() / 3600
        cur = nxt
    return total


def ivr_silence(db, tenant, now: Optional[datetime] = None) -> Optional[dict]:
    """{provider, label, last_call_at, silent_hours, messages, normal_calls_per_day, threshold_hours} when the tenant's
    active IVR looks dead, else None. Reads the Call and Message rows themselves (the record), no other source."""
    from sqlalchemy import func

    from app.models.call import Call
    from app.models.conversation import ChannelType, Message, MessageDirection
    from app.models.integration import Integration

    provider = (getattr(tenant, "ivr_provider", None) or "").strip()
    if not provider:
        return None
    if db.query(Integration.id).filter_by(tenant_id=tenant.id, kind=provider, status="active").first() is None:
        return None
    now = now or datetime.now(timezone.utc)
    calls = db.query(func.count(Call.id)).filter(Call.tenant_id == tenant.id, Call.ivr_provider == provider,
                                                 Call.created_at >= now - timedelta(days=IVR_BASELINE_DAYS)).scalar() or 0
    if calls < IVR_MIN_BASELINE_CALLS:
        return None
    last = db.query(func.max(Call.created_at)).filter(Call.tenant_id == tenant.id, Call.ivr_provider == provider).scalar()
    if last is None:
        return None
    last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
    open_hours = IVR_BASELINE_DAYS * (BUSINESS_HOURS[1] - BUSINESS_HOURS[0])
    threshold = max(IVR_MIN_SILENT_HOURS, IVR_GAP_FACTOR * open_hours / calls)
    silent = _business_hours_between(last, now)
    if silent < threshold:
        return None
    messages = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tenant.id, Message.direction == MessageDirection.INBOUND, Message.created_at > last,
        Message.channel.in_([ChannelType.WHATSAPP, ChannelType.INSTAGRAM])).scalar() or 0
    if messages < IVR_MIN_MESSAGES:
        return None                    # a genuinely quiet business, not a dead line
    return {"provider": provider, "label": label(provider), "last_call_at": last, "silent_hours": round(silent, 1),
            "messages": int(messages), "normal_calls_per_day": round(calls / IVR_BASELINE_DAYS, 1),
            "threshold_hours": round(threshold, 1)}
