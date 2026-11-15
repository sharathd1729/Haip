"""Instagram welcome questions and chat menu (Instagram Automations v2, phase 5).

Workspace-level, stored in tenants.brand_config["instagram_welcome"] (schemas/ig_automation.IgWelcome) and pushed to
Instagram's chat profile (ice breakers + persistent menu). A question or menu item linked to an automation sends the
postback igauto:<rule>:start, which runs that automation as if it was triggered in an open chat (ig_suggest.route);
an unlinked one sends its text as an ordinary message, so keyword rules and the AI answer it. Links open in a browser.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.schemas.ig_automation import IgWelcome
from app.services import ig_automation as engine

logger = logging.getLogger(__name__)

KEY = "instagram_welcome"


class WelcomeError(ValueError):
    pass


def get(tenant) -> dict:
    raw = (getattr(tenant, "brand_config", None) or {}).get(KEY) or {}
    try:
        return IgWelcome(**raw).model_dump()
    except Exception:  # noqa: BLE001 -- a hand-edited value should never break the page
        return IgWelcome().model_dump()


def _check_rules(db: Session, tenant_id: str, cfg: IgWelcome) -> None:
    wanted = {q.rule_id for q in cfg.questions if q.rule_id} | {m.rule_id for m in cfg.menu if m.rule_id}
    if not wanted:
        return
    found = {
        r
        for (r,) in db.query(AutomationRule.id).filter(
            AutomationRule.tenant_id == tenant_id,
            AutomationRule.id.in_(wanted),
            AutomationRule.action == "send_instagram_quick_reply",
        )
    }
    missing = wanted - found
    if missing:
        raise WelcomeError("One of the linked automations no longer exists. Pick it again.")


def _profile(cfg: IgWelcome) -> tuple[list[dict], list[dict]]:
    ice = [
        {"question": q.question, "payload": engine._payload(q.rule_id, "start") if q.rule_id else f"igwelcome:q{i}"}
        for i, q in enumerate(cfg.questions)
    ]
    menu = []
    for i, m in enumerate(cfg.menu):
        if m.kind == "link":
            menu.append({"type": "web_url", "title": m.title, "url": m.url})
        else:
            payload = engine._payload(m.rule_id, "start") if m.kind == "automation" else f"igwelcome:m{i}"
            menu.append({"type": "postback", "title": m.title, "payload": payload})
    return ice, menu


def save(db: Session, tenant, actor_user_id: str, data: dict) -> dict:
    """Validate, store, push to Instagram, audit. Returns {settings, pushed, error}. Commits.
    Stored even when Instagram refuses, so the owner can retry after reconnecting."""
    cfg = IgWelcome(**(data or {}))
    _check_rules(db, tenant.id, cfg)
    before = get(tenant)
    brand = dict(tenant.brand_config or {})
    brand[KEY] = cfg.model_dump()
    tenant.brand_config = brand  # a new dict: JSON columns do not track in-place changes
    from app.core.audit import append_audit

    append_audit(
        db,
        tenant_id=tenant.id,
        action="instagram.welcome_updated",
        actor_user_id=actor_user_id,
        target_type="tenant",
        target_id=tenant.id,
        payload={"before": before, "after": brand[KEY]},
    )
    db.commit()
    adapter = engine._adapter(db, tenant.id)
    if adapter is None:
        return {"settings": brand[KEY], "pushed": False, "error": "Instagram isn't connected."}
    ice, menu = _profile(cfg)
    try:
        adapter.set_chat_profile(ice, menu)
    except Exception as exc:  # noqa: BLE001 -- shown to the owner; Meta's reason, never a token (meta_graph sanitises)
        logger.warning("ig_welcome_push_failed tenant=%s: %s", tenant.id, exc)
        return {"settings": brand[KEY], "pushed": False, "error": str(exc)[:300]}
    return {"settings": brand[KEY], "pushed": True, "error": None}
