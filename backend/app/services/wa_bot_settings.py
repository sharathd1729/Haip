"""WhatsApp hours and welcome settings, stored in ``tenants.brand_config.wa_bot`` (no migration):

  hours            weekly open/close per weekday (or closed) + holidays (whole days closed), in the workspace timezone.
                   THE team hours: away keyword replies (wa_keyword_replies, hours "closed"/"open") and Ask a manager
                   (agent_consult_settings.in_business_hours / next_opening) both read ``is_open`` / ``next_opening``.
                   Never saved = the old single window (agent_consult business_start/business_end) on every weekday.
  welcome          a fixed first reply to a brand-new contact (services/wa_bot_replies.py)
  location_reply   the reply to a shared location pin
  opt_confirm      the STOP / START confirmation text (services/opt_out_responder.py)

Owner and manager change them (PUT /whatsapp/bot-settings; PATCH /tenants/me refuses the key). Every change is a chained
audit row with the sections before and after.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.tenant_tz import get_tz
from app.schemas.wa_bot import DAYS, DayHours, Hours, LocationReply, OptConfirm, WaBotSettingsIn, Welcome

KEY = "wa_bot"

DEFAULTS: dict[str, dict[str, Any]] = {
    "welcome": {"enabled": False, "buttons": [], "also_when_ai_replies": True,
                "text": "Hi {first_name}, welcome! Thanks for writing to us. Tell us your dates and how many guests, "
                        "and we'll help you plan your stay."},
    "location_reply": {"enabled": False, "map_link": "",
                       "text": "Thanks for sharing your location, {first_name}! Our team will send you the best route shortly."},
    "opt_confirm": {"custom": True,
                    "stop_text": "Done. You won't get offers from us on WhatsApp any more. Reply START any time to hear from us again.",
                    "start_text": "Welcome back! You'll get our offers and updates on WhatsApp again. Reply STOP any time to stop them."},
}
_MODELS: dict[str, type[BaseModel]] = {"hours": Hours, "welcome": Welcome, "location_reply": LocationReply,
                                       "opt_confirm": OptConfirm}


def _cfg(tenant) -> dict:
    cfg = getattr(tenant, "brand_config", None) or {}
    return cfg if isinstance(cfg, dict) else {}


def _raw(tenant) -> dict:
    raw = _cfg(tenant).get(KEY)
    return raw if isinstance(raw, dict) else {}


def _hours_default(tenant) -> dict:
    """The old single daily window (agent_consult business_start/end) on every weekday, no holidays."""
    old = _cfg(tenant).get("agent_consult")
    old = old if isinstance(old, dict) else {}
    try:
        day = DayHours(open=old.get("business_start", "09:00"), close=old.get("business_end", "21:00")).model_dump()
    except ValidationError:
        day = DayHours().model_dump()
    return {"weekly": {d: dict(day) for d in DAYS}, "holidays": []}


def get(tenant) -> dict:
    """Effective settings: each stored section if it still validates, else its default. Never raises on odd stored data."""
    raw = _raw(tenant)
    out: dict[str, Any] = {}
    for section, model in _MODELS.items():
        default = _hours_default(tenant) if section == "hours" else DEFAULTS[section]
        stored = raw.get(section)
        try:
            out[section] = model.model_validate(stored).model_dump(mode="json") if isinstance(stored, dict) else default
        except ValidationError:
            out[section] = default
    return out


# ── hours ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def _window(hours: dict, d: date) -> Optional[tuple[int, int]]:
    """(open, close) minutes for that local date, or None when closed (off day or holiday)."""
    if d.isoformat() in {h["date"] for h in hours["holidays"]}:
        return None
    day = hours["weekly"][DAYS[d.weekday()]]
    return None if day["closed"] else (_minutes(day["open"]), _minutes(day["close"]))


def is_open(tenant, now: Optional[datetime] = None) -> bool:
    """True inside today's window, or inside yesterday's window that runs past midnight."""
    hours = get(tenant)["hours"]
    local = (now or datetime.now(timezone.utc)).astimezone(get_tz(tenant))
    m = local.hour * 60 + local.minute
    today = _window(hours, local.date())
    if today is not None:
        o, c = today
        if o == c or (o <= m < c if o < c else m >= o):
            return True
    yesterday = _window(hours, local.date() - timedelta(days=1))
    return yesterday is not None and yesterday[0] > yesterday[1] and m < yesterday[1]


def next_opening(tenant, now: Optional[datetime] = None) -> datetime:
    """The next time a window opens (UTC), strictly after ``now``. Skips off days and holidays (looks 3 weeks ahead)."""
    tz = get_tz(tenant)
    hours = get(tenant)["hours"]
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    for i in range(22):
        d = local.date() + timedelta(days=i)
        w = _window(hours, d)
        if w is None:
            continue
        at = datetime.combine(d, time(w[0] // 60, w[0] % 60), tzinfo=tz)
        if at > local:
            return at.astimezone(timezone.utc)
    return (local + timedelta(days=1)).astimezone(timezone.utc)   # closed every day: promise tomorrow rather than never


def hours_summary(tenant) -> str:
    """"Mon-Fri 09:00-21:00 · Sat-Sun closed · 2 holidays" for hints on other screens."""
    hours = get(tenant)["hours"]
    label = lambda d: "closed" if d["closed"] else (f"{d['open']}-{d['close']}" if d["open"] != d["close"] else "open all day")
    parts: list[list] = []
    for day in DAYS:
        text = label(hours["weekly"][day])
        if parts and parts[-1][2] == text:
            parts[-1][1] = day
        else:
            parts.append([day, day, text])
    out = " · ".join((a.title() if a == b else f"{a.title()}-{b.title()}") + " " + t for a, b, t in parts)
    today = datetime.now(get_tz(tenant)).date().isoformat()
    upcoming = [h for h in hours["holidays"] if h["date"] >= today]
    return out + (f" · {len(upcoming)} holiday{'s' if len(upcoming) != 1 else ''}" if upcoming else "")


def view(tenant) -> dict:
    return {**get(tenant), "timezone": str(get_tz(tenant)), "hours_summary": hours_summary(tenant), "open_now": is_open(tenant)}


def update(db: Session, tenant, actor_id: str, body: WaBotSettingsIn) -> dict:
    """Replace each section given, audit it. Returns {section: {from, to}}. The caller commits."""
    current = get(tenant)
    stored = dict(_raw(tenant))
    changes: dict = {}
    for section in _MODELS:
        value = getattr(body, section)
        if value is None:
            continue
        new = value.model_dump(mode="json")
        if new != current[section] or section not in stored:
            changes[section] = {"from": current[section], "to": new}
            stored[section] = new
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = stored
        tenant.brand_config = cfg                    # a new dict: JSON columns do not track in-place mutation
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="whatsapp.bot_settings_changed",
                     target_type="tenant", target_id=tenant.id, payload={"changes": changes})
    return changes
