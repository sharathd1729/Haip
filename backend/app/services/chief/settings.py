"""The AI Executive's owner settings, ``tenants.brand_config.chief`` (schema schemas/chief.ChiefSettings; no migration).

OFF for every workspace until the owner turns it on. Only the owner changes it (PUT /chief/settings, audited
``chief.settings_changed``); PATCH /tenants/me refuses the key.
"""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.schemas.chief import ChiefSettings

KEY = "chief"


def get(tenant) -> ChiefSettings:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    if not isinstance(raw, dict):
        return ChiefSettings()
    try:
        return ChiefSettings.model_validate(raw)
    except ValidationError:
        return ChiefSettings()


def update(db: Session, tenant, actor_id: str | None, new: ChiefSettings) -> dict:
    before, after = get(tenant).model_dump(), new.model_dump()
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = after
        tenant.brand_config = cfg
        append_audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=actor_id,
            action="chief.settings_changed",
            target_type="tenant",
            target_id=tenant.id,
            payload={"changes": changes},
        )
    return changes
