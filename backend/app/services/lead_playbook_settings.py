"""The owner's lead playbook settings, stored in ``tenants.brand_config.lead_playbooks`` (no migration needed):

  {"enabled": true,                         workspace master switch (default on, every playbook still off by itself)
   "guest_cap_hours": 4,                    at most one playbook WhatsApp per guest in this many hours
   "daily_cap": 150,                        at most this many playbook WhatsApps per workspace per day
   "playbooks": {"missed_inbound_call": {"enabled": false, "delay_seconds": 45, "callback_minutes": 15}, ...}}

Only owners and managers change it, through PUT /workflows/settings (PATCH /tenants/me refuses the key). Every change is a
chained audit row with before/after values.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.services import lead_playbook_catalog as cat

KEY = "lead_playbooks"

# What an owner may set per playbook, and its bounds.
_INT_FIELDS = {"delay_seconds": (15, 600), "callback_minutes": (5, 240)}
_WORKSPACE_INT = {"guest_cap_hours": (1, 72), "daily_cap": (1, 2000), "bridge_quiet_minutes": (0, 1440),
                  "quiet_start_hour": (0, 23), "quiet_end_hour": (0, 23)}
_WORKSPACE_BOOL = ("enabled", "staff_whatsapp")


def _raw(tenant) -> dict:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    return raw if isinstance(raw, dict) else {}


def get(tenant) -> dict:
    """The effective settings: stored values over the catalogue defaults. Never raises on odd stored data."""
    raw = _raw(tenant)
    out: dict[str, Any] = {}
    for k, default in cat.WORKSPACE_DEFAULTS.items():
        v = raw.get(k, default)
        out[k] = v if isinstance(v, type(default)) else default
    stored = raw.get("playbooks") if isinstance(raw.get("playbooks"), dict) else {}
    pbs: dict[str, dict] = {}
    for p in cat.CATALOG:
        mine = stored.get(p["key"]) if isinstance(stored.get(p["key"]), dict) else {}
        merged = dict(p["defaults"])
        for k, default in p["defaults"].items():
            if k in mine and isinstance(mine[k], type(default)):
                merged[k] = mine[k]
        if not p["built"]:
            merged["enabled"] = False
        pbs[p["key"]] = merged
    out["playbooks"] = pbs
    return out


def playbook(tenant, key: str) -> dict:
    """One playbook's effective settings, with ``active`` = the workspace switch and the playbook switch are both on."""
    s = get(tenant)
    pb = dict(s["playbooks"].get(key) or {})
    pb["active"] = bool(s["enabled"] and pb.get("enabled") and key in cat.BUILT)
    return pb


def _check_int(name: str, value, bounds: tuple[int, int]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number")
    lo, hi = bounds
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return value


def update(db: Session, tenant, actor_id: str, patch: dict) -> dict:
    """Apply a partial change: {"enabled"?, "guest_cap_hours"?, "daily_cap"?, "playbooks"?: {key: {field: value}}}.
    Raises ValueError with a plain message on anything invalid. Returns {path: {from, to}}. The caller commits."""
    before = get(tenant)
    raw = dict(_raw(tenant))
    changes: dict = {}

    for name in _WORKSPACE_BOOL:
        if name in patch:
            if not isinstance(patch[name], bool):
                raise ValueError(f"{name} must be true or false")
            raw[name] = patch[name]
    for name, bounds in _WORKSPACE_INT.items():
        if name in patch:
            raw[name] = _check_int(name, patch[name], bounds)

    pb_patch = patch.get("playbooks") or {}
    if not isinstance(pb_patch, dict):
        raise ValueError("playbooks must be an object")
    stored = dict(raw.get("playbooks") or {}) if isinstance(raw.get("playbooks"), dict) else {}
    for key, fields in pb_patch.items():
        meta = cat.BY_KEY.get(key)
        if meta is None:
            raise ValueError(f"Unknown playbook: {key}")
        if not isinstance(fields, dict):
            raise ValueError(f"{key}: settings must be an object")
        mine = dict(stored.get(key) or {}) if isinstance(stored.get(key), dict) else {}
        for field, value in fields.items():
            if field == "enabled":
                if not isinstance(value, bool):
                    raise ValueError(f"{key}.enabled must be true or false")
                if value and not meta["built"]:
                    raise ValueError(f"{meta['name']} is not available yet")
                mine["enabled"] = value
            elif field == "mode" and "mode" in meta["defaults"]:
                if value not in cat.FOLLOWUP_MODES:
                    raise ValueError(f"{key}.mode must be one of {', '.join(cat.FOLLOWUP_MODES)}")
                mine["mode"] = value
            elif field in _INT_FIELDS and field in meta["defaults"]:
                mine[field] = _check_int(f"{key}.{field}", value, _INT_FIELDS[field])
            else:
                raise ValueError(f"{key}: {field} cannot be changed")
        stored[key] = mine
    raw["playbooks"] = stored

    cfg = dict(tenant.brand_config or {})
    cfg[KEY] = raw
    tenant.brand_config = cfg                      # a new dict: JSON columns do not track in-place mutation
    after = get(tenant)
    for k in cat.WORKSPACE_DEFAULTS:
        if before[k] != after[k]:
            changes[k] = {"from": before[k], "to": after[k]}
    for key, vals in after["playbooks"].items():
        for field, v in vals.items():
            old = before["playbooks"][key].get(field)
            if old != v:
                changes[f"{key}.{field}"] = {"from": old, "to": v}
    if changes:
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="workflows.settings_changed",
                     target_type="tenant", target_id=tenant.id, payload={"changes": changes})
    return changes


def guarded_keys(incoming: Optional[dict]) -> bool:
    """True when a brand_config write tries to set the playbook settings (PATCH /tenants/me must refuse it)."""
    return isinstance(incoming, dict) and KEY in incoming
