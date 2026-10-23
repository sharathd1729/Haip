"""The learning loop's settings (``brand_config.learning``, schemas/learning.LearningSettings) and the BASE values of the controls
the experiments change that have no other home (``brand_config.learning_base``):

  price_disclosure_packages  published packages whose price the AI may state ("from Rs X + GST") while the workspace is in
                             handoff mode
  route_map                  {guest ask: published destination key}, e.g. {"goa": "western-ghats-sea"}
  consult_price_above        a quote total above which a price question is handed to a person (None = off)
  followup_first_hours       {playbook key: hours before the first follow-up} (None = the code default)

The sales playbook keeps its own home (sales_playbook). Only the owner changes the settings (GET/PUT /ai/learning-settings,
audited ``learning.settings_changed``); PATCH /tenants/me refuses ``learning``. Turning ``paused`` on stops every running
experiment at once (experiments.pause_all).
"""
from __future__ import annotations

from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.schemas.learning import AREAS, LEVELS, LearningSettings

KEY = "learning"
BASE_KEY = "learning_base"
BASE_DEFAULTS = {"price_disclosure_packages": [], "route_map": {}, "consult_price_above": None, "followup_first_hours": {}}


def get(tenant) -> LearningSettings:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    if not isinstance(raw, dict):
        return LearningSettings()
    try:
        return LearningSettings.model_validate(raw)
    except ValidationError:
        return LearningSettings()


def level(tenant, area: str) -> str:
    s = get(tenant)
    lvl = s.areas.get(area, AREAS.get(area, ("watch",))[0])
    ceiling = AREAS.get(area, ("watch", "watch"))[1]
    return lvl if LEVELS.index(lvl) <= LEVELS.index(ceiling) else ceiling


def base(tenant) -> dict:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(BASE_KEY) if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in BASE_DEFAULTS.items()}
    for k, default in BASE_DEFAULTS.items():
        if k in raw and (default is None or isinstance(raw[k], type(default))):
            out[k] = raw[k]                       # a stored value of the wrong shape is ignored, never half-applied
    return out


def set_base(tenant, key: str, value) -> None:
    cfg = dict(tenant.brand_config or {})
    cur = dict(cfg.get(BASE_KEY) or {})
    cur[key] = value
    cfg[BASE_KEY] = cur
    tenant.brand_config = cfg


def update(db: Session, tenant, actor_id: Optional[str], new: LearningSettings, *, actor: Optional[str] = None) -> dict:
    before, after = get(tenant).model_dump(), new.model_dump()
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = after
        tenant.brand_config = cfg
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="learning.settings_changed", target_type="tenant",
                     target_id=tenant.id, payload={"changes": changes, **({"actor": actor} if actor else {})})
        if after["paused"] and not before["paused"]:
            from app.services.learning import experiments
            experiments.pause_all(db, tenant, actor_id)
    return changes


def view(tenant) -> dict:
    return {"settings": get(tenant).model_dump(), "defaults": LearningSettings().model_dump(),
            "areas": [{"key": k, "default": d, "max": m} for k, (d, m) in AREAS.items()], "base": base(tenant)}
