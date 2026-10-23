"""The analyst's owner settings, ``tenants.brand_config.analyst`` (schema schemas/analyst.AnalystSettings; no migration).

Default: OFF for every workspace (Rathaa is switched on by scripts/seed_ratha_analyst.py). Daily pulse 09:00, weekly brief
Monday 08:30, monthly review on the 1st at 08:30, all local time (IST); delivery by email / WhatsApp off until the owner turns
it on (WhatsApp also needs the Meta-approved template). Only the owner changes it (PUT /analyst/settings, audited
``analyst.settings_changed``); PATCH /tenants/me refuses the key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.schemas.analyst import AnalystSettings

KEY = "analyst"
SCHEDULE_FIELD = {"daily_pulse": "daily", "weekly_brief": "weekly", "monthly_review": "monthly"}


def get(tenant) -> AnalystSettings:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    if not isinstance(raw, dict):
        return AnalystSettings()
    try:
        return AnalystSettings.model_validate(raw)
    except ValidationError:
        return AnalystSettings()


def update(db: Session, tenant, actor_id: Optional[str], new: AnalystSettings, *, actor: Optional[str] = None) -> dict:
    before, after = get(tenant).model_dump(), new.model_dump()
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = after
        tenant.brand_config = cfg
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="analyst.settings_changed", target_type="tenant",
                     target_id=tenant.id, payload={"changes": changes, **({"actor": actor} if actor else {})})
    return changes


def is_due(s: AnalystSettings, kind: str, local: datetime) -> bool:
    """True once the kind's time has passed in its period (Monday for the weekly brief, the 1st for the monthly review). The
    report's period uniqueness (one per kind + period start) makes a later tick in the same period a no-op; a tick later in
    the week / month still catches up a missed one."""
    if not s.enabled:
        return False
    sched = getattr(s, SCHEDULE_FIELD[kind])
    if not sched.on:
        return False
    hh, mm = (int(x) for x in sched.time.split(":"))
    passed_today = (local.hour, local.minute) >= (hh, mm)
    if kind == "daily_pulse":
        return passed_today
    if kind == "weekly_brief":
        return local.weekday() > 0 or passed_today
    return local.day > 1 or passed_today
