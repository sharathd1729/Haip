"""The owner's "Ask a manager" settings, stored in ``tenants.brand_config.agent_consult`` (no migration needed):

  enabled                 true   consults open when a trigger fires (off = today's behaviour: drafts wait in the Inbox)
  business_start / _end   "09:00" / "21:00": legacy single window, only used until the weekly hours in wa_bot_settings are
                          saved (they are the team hours now; in_business_hours / next_opening read them)
  sla_minutes             15     how long each level has to answer inside business hours
  offhours_reply_minutes  60     outside hours, the answer is promised this long after opening time ("by 10 am")
  send_holding_reply      true   send ONE honest "let me check with the team" reply
  holding_text            in hours; {minutes}
  holding_text_offhours   outside hours; {time} and {day} ("today" / "tomorrow" / "on Monday")

Only the owner changes them (PUT /ai/consult-settings; PATCH /tenants/me refuses the key). Every change is a chained audit
row with before/after values.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.tenant_tz import get_tz

KEY = "agent_consult"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "business_start": "09:00",
    "business_end": "21:00",
    "sla_minutes": 15,
    "offhours_reply_minutes": 60,
    "send_holding_reply": True,
    "holding_text": "Let me check this with our team and come back to you within {minutes} minutes.",
    "holding_text_offhours": "Thanks for your message! Our team is away right now. I'll check this with them and come back "
                             "to you by {time} {day}.",
}


def _raw(tenant) -> dict:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    return raw if isinstance(raw, dict) else {}


def get(tenant) -> dict:
    """Effective settings: stored values of the right type over the defaults. Never raises on odd stored data."""
    raw = _raw(tenant)
    out = {}
    for k, default in DEFAULTS.items():
        v = raw.get(k, default)
        ok = isinstance(v, bool) if isinstance(default, bool) else (
            isinstance(v, int) and not isinstance(v, bool) if isinstance(default, int) else isinstance(v, str))
        out[k] = v if ok else default
    return out


def in_business_hours(tenant, now: Optional[datetime] = None) -> bool:
    """The workspace's weekly hours + holidays (wa_bot_settings: the one place team hours live)."""
    from app.services import wa_bot_settings
    return wa_bot_settings.is_open(tenant, now or datetime.now(timezone.utc))


def next_opening(tenant, now: Optional[datetime] = None) -> datetime:
    """The next time business hours start (UTC), skipping off days and holidays."""
    from app.services import wa_bot_settings
    return wa_bot_settings.next_opening(tenant, now or datetime.now(timezone.utc))


def sla_due(tenant, now: Optional[datetime] = None) -> datetime:
    """When the first level must have answered: now + SLA inside hours, else opening time + the off-hours promise."""
    now = now or datetime.now(timezone.utc)
    s = get(tenant)
    if in_business_hours(tenant, now):
        return now + timedelta(minutes=int(s["sla_minutes"]))
    return next_opening(tenant, now) + timedelta(minutes=int(s["offhours_reply_minutes"]))


def holding_text(tenant, now: Optional[datetime] = None) -> str:
    """The one honest holding reply for this moment, with its placeholders filled. A bad template falls back to the default."""
    now = now or datetime.now(timezone.utc)
    s = get(tenant)
    if in_business_hours(tenant, now):
        tpl, default = s["holding_text"], DEFAULTS["holding_text"]
        values = {"minutes": int(s["sla_minutes"]), "time": "", "day": ""}
    else:
        tz = get_tz(tenant)
        due = sla_due(tenant, now).astimezone(tz)
        local_now = now.astimezone(tz)
        hour = due.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
        gap = (due.date() - local_now.date()).days
        values = {"minutes": int(s["sla_minutes"]), "time": hour,
                  "day": "today" if gap <= 0 else "tomorrow" if gap == 1 else due.strftime("on %A")}
        tpl, default = s["holding_text_offhours"], DEFAULTS["holding_text_offhours"]
    try:
        return tpl.format(**values).strip()
    except (KeyError, IndexError, ValueError):
        return default.format(**values).strip()


def view(tenant) -> dict:
    s = get(tenant)
    from app.services import wa_bot_settings
    return {**s, "timezone": str(get_tz(tenant)), "hours_summary": wa_bot_settings.hours_summary(tenant), "preview": {"in_hours": holding_text(tenant, _sample(tenant, True)),
                                                             "off_hours": holding_text(tenant, _sample(tenant, False))}}


def _sample(tenant, inside: bool) -> datetime:
    """The next whole hour inside (or outside) business hours, for the settings preview."""
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for h in range(1, 24 * 22):
        at = base + timedelta(hours=h)
        if in_business_hours(tenant, at) == inside:
            return at
    return base


def update(db: Session, tenant, actor_id: str, changes_in: dict) -> dict:
    """Apply the owner's change and audit it. Returns {field: {from, to}}. The caller commits."""
    current = get(tenant)
    changes: dict = {}
    stored = dict(_raw(tenant))
    for k, v in changes_in.items():
        if v is None or k not in DEFAULTS:
            continue
        if current.get(k) != v:
            changes[k] = {"from": current.get(k), "to": v}
            stored[k] = v
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = stored
        tenant.brand_config = cfg                    # a new dict: JSON columns do not track in-place mutation
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="ai.consult_settings_changed",
                     target_type="tenant", target_id=tenant.id, payload={"changes": changes})
    return changes
