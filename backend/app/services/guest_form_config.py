"""The workspace's own guest details form, ``tenants.brand_config.guest_form`` (schema schemas/guest_form_config; no
migration). Workspace redesign Phase 4.

Read by ops_guest_form (the guest's page and the submit check). Changed only through PUT /ops/guest-form/config
(ops.manage, audited ``ops.guest_form_changed``); PATCH /tenants/me refuses the key. A workspace that never saved one
gets the defaults, which ask exactly what the form asked before it could be changed.

Answers to the owner's own questions are stored with the question's label at the time (``data.answers``), so a later
edit or deletion never changes what a guest said.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.schemas.guest_form_config import GuestFormConfig

KEY = "guest_form"
YES_NO = {"yes": "Yes", "no": "No"}


def get(tenant) -> GuestFormConfig:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    if not isinstance(raw, dict):
        return GuestFormConfig()
    try:
        return GuestFormConfig.model_validate(raw)
    except ValidationError:
        return GuestFormConfig()


def update(db: Session, tenant, actor_id: str | None, new: GuestFormConfig) -> dict:
    before, after = get(tenant).model_dump(), new.model_dump()
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = after
        tenant.brand_config = cfg
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="ops.guest_form_changed",
                     target_type="tenant", target_id=tenant.id, payload={"changes": changes})
    return changes


def answers(cfg: GuestFormConfig, raw: dict[str, str], errors: list[str]) -> list[dict]:
    """Check the guest's answers to the owner's questions; unknown keys are ignored. Returns [{id, label, kind, value}]."""
    out = []
    for q in cfg.questions:
        value = " ".join(str(raw.get(q.id) or "").split())[:500]
        if not value:
            if q.required:
                errors.append(f"Please answer: {q.label}")
            continue
        if q.kind == "yesno":
            if value.lower() not in YES_NO:
                errors.append(f"{q.label}: choose yes or no")
                continue
            value = YES_NO[value.lower()]
        elif q.kind == "choice":
            match = next((o for o in q.options if o.lower() == value.lower()), None)
            if match is None:
                errors.append(f"{q.label}: choose one of the options")
                continue
            value = match
        elif q.kind == "date":
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{q.label}: enter a date")
                continue
        out.append({"id": q.id, "label": q.label, "kind": q.kind, "value": value})
    return out
