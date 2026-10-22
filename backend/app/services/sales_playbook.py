"""The owner's sales playbook, stored in ``tenants.brand_config.sales_playbook`` (no migration needed; schema
schemas/sales_playbook.py). Empty by default: the prompts then behave exactly as before.

Read by the concierge reply prompt (concierge_reply.jinja, SALES PLAYBOOK block; the sales agent speaks through the same
prompt) and the follow-up draft prompt (lead_followup_draft: follow_up_style). The playbook shapes HOW the AI sells; it never
overrides the data, the price rules or the code guards (a playbook line cannot make the AI state a price). Only the owner
changes it (GET/PUT /ai/sales-playbook; PATCH /tenants/me refuses the key); every change is a chained audit row.
Rathaa's master: scripts/seed_ratha_playbook.py (dry run unless --apply).
"""
from __future__ import annotations

from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.schemas.sales_playbook import SalesPlaybook

KEY = "sales_playbook"


def get(tenant) -> SalesPlaybook:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    if not isinstance(raw, dict):
        return SalesPlaybook()
    try:
        return SalesPlaybook.model_validate(raw)
    except ValidationError:
        return SalesPlaybook()                    # stored data that no longer validates is ignored, never half-applied


def is_empty(pb: SalesPlaybook) -> bool:
    return pb == SalesPlaybook()


def prompt_view(tenant) -> Optional[dict]:
    """What the concierge prompt renders, or None when the owner has not written a playbook."""
    pb = get(tenant)
    return None if is_empty(pb) else pb.model_dump()


def follow_up_style(tenant) -> str:
    return get(tenant).follow_up_style


def view(tenant) -> dict:
    return {"playbook": get(tenant).model_dump(), "empty": is_empty(get(tenant))}


def update(db: Session, tenant, actor_id: Optional[str], new: SalesPlaybook, *, actor: Optional[str] = None) -> dict:
    """Replace the playbook and audit what changed. Returns {field: {from, to}}. The caller commits."""
    before = get(tenant).model_dump()
    after = new.model_dump()
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    if changes:
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = after
        tenant.brand_config = cfg
        payload = {"changes": changes, **({"actor": actor} if actor else {})}
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="ai.sales_playbook_changed", target_type="tenant",
                     target_id=tenant.id, payload=payload)
    return changes
