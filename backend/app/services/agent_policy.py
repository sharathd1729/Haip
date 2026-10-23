"""Who may decide what: the owner's AI action policy, stored in ``tenants.brand_config.agent_policy`` (no migration needed).

Each ACTION CLASS has a mode:
  autonomous          the AI may do it on its own (every code guard still applies: a policy never loosens a guard)
  draft_for_approval  the AI prepares it and a person approves it before anything goes out (no holding reply, no consult)
  consult             the AI does not do it: it holds its reply, tells the guest the team is checking and asks a person
                      (Ask a manager, agent_consult_flow)

Defaults: answer_faq / suggest_kit autonomous; quote_published_price autonomous ONLY when price_disclosure = grounded, else
consult; send_payment_link and hold_dates draft_for_approval; discount, custom_route, b2b, cancellation_refund, complaint consult.

Enforced in code: the concierge reply path (agent_consult_flow.check_turn -> apply()) and the sales agent before it sends a
quote + payment link (sales_agent_service._holds -> allows()). Nothing today places a date hold on its own; hold_dates is read
by any future step that would. Only the owner changes it (GET/PUT /ai/agent-policy; PATCH /tenants/me refuses the key); every
change is a chained audit row with before/after values.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit

KEY = "agent_policy"
MODES = ("autonomous", "draft_for_approval", "consult")
ACTION_CLASSES: dict[str, str] = {
    "answer_faq": "Answer questions from your knowledge base and published data",
    "quote_published_price": "State a published price",
    "suggest_kit": "Suggest a kit or add-on (Culinary, Wellness, Adventure)",
    "send_payment_link": "Send a payment link",
    "hold_dates": "Hold dates for a guest",
    "discount": "Discuss a discount",
    "custom_route": "Plan a custom or unpublished route",
    "b2b": "Partner / travel-agent (B2B) rates",
    "cancellation_refund": "Cancellations and refunds",
    "complaint": "Complaints",
}
_FIXED_DEFAULTS = {
    "answer_faq": "autonomous", "suggest_kit": "autonomous", "send_payment_link": "draft_for_approval",
    "hold_dates": "draft_for_approval", "discount": "consult", "custom_route": "consult", "b2b": "consult",
    "cancellation_refund": "consult", "complaint": "consult",
}
# Which trigger codes (agent_escalation_rules.REASONS) belong to which class: the class's mode decides whether they still ask.
REASON_CLASS = {
    "discount_request": "discount", "custom_route": "custom_route", "b2b_partner": "b2b", "b2b_only": "b2b",
    "refund": "cancellation_refund", "cancellation": "cancellation_refund", "complaint": "complaint",
    "price_handoff": "quote_published_price",
}
_KIT_RE = re.compile(r"\b(culinary|wellness|adventure)\s+kit\b|\bkits?\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"(₹|\brs\.?\s?)\s?\d", re.IGNORECASE)


def defaults(tenant, price_mode: Optional[str] = None) -> dict:
    """``price_mode`` = this turn's mode when the learning loop made it grounded for one published package (resolver)."""
    from app.services.price_policy import price_mode as tenant_price_mode
    out = dict(_FIXED_DEFAULTS)
    out["quote_published_price"] = "autonomous" if (price_mode or tenant_price_mode(tenant)) == "grounded" else "consult"
    return {k: out[k] for k in ACTION_CLASSES}


def _raw(tenant) -> dict:
    cfg = getattr(tenant, "brand_config", None) or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    return raw if isinstance(raw, dict) else {}


def get(tenant, price_mode: Optional[str] = None) -> dict:
    """Effective modes: the owner's stored value when valid, else the default, then CAPPED by the learning loop's autonomy
    level of the class's area (learning_limits.cap: act = as set, suggest = at most draft_for_approval, watch = consult). The
    cap only ever makes a mode stricter. Never raises on odd stored data."""
    stored = _raw(tenant).get("modes")
    stored = stored if isinstance(stored, dict) else {}
    out = defaults(tenant, price_mode)
    for k in ACTION_CLASSES:
        if stored.get(k) in MODES:
            out[k] = stored[k]
    try:
        from app.services.learning import limits
        out = limits.cap(tenant, out)
    except Exception:  # noqa: BLE001 -- the owner's modes stand
        pass
    return out


def mode_for(tenant, action: str) -> str:
    return get(tenant).get(action, "consult")


def allows(db: Session, tenant_or_id, action: str) -> bool:
    """True when the AI may do ``action`` on its own."""
    tenant = tenant_or_id
    if isinstance(tenant_or_id, str):
        from app.models.tenant import Tenant
        tenant = db.query(Tenant).filter_by(id=tenant_or_id).first()
    return tenant is not None and mode_for(tenant, action) == "autonomous"


def classes_for_turn(intent: Optional[str], reply_text: str, reasons: list[str]) -> list[str]:
    """The action classes this reply would perform, deterministically (never the model's own say)."""
    out = [REASON_CLASS[r] for r in reasons if r in REASON_CLASS]
    if _MONEY_RE.search(reply_text or ""):                # the reply itself states a figure
        out.append("quote_published_price")
    if _KIT_RE.search(reply_text or ""):
        out.append("suggest_kit")
    if not out:
        out.append("answer_faq")
    return list(dict.fromkeys(out))


def apply(tenant, intent: Optional[str], reply_text: str, reasons: list[str], *,
          price_mode: Optional[str] = None) -> tuple[list[str], bool, list[str]]:
    """(reasons to consult on, hold as a draft?, policy notes). A mapped trigger whose class the owner made autonomous or
    draft_for_approval stops asking; a class set to consult that no trigger caught adds ``policy_consult``."""
    modes = get(tenant, price_mode)
    kept, hold, notes = [], False, []
    for r in reasons:
        cls = REASON_CLASS.get(r)
        mode = modes.get(cls) if cls else "consult"
        if mode == "consult":
            kept.append(r)
        elif mode == "draft_for_approval":
            hold = True
            notes.append(f"policy: {cls} needs approval")
    for cls in classes_for_turn(intent, reply_text, reasons):
        mode = modes.get(cls, "consult")
        if mode == "consult" and not any(REASON_CLASS.get(r) == cls for r in kept):
            kept.append("policy_consult")
            notes.append(f"policy: {cls} is asked of a person")
        elif mode == "draft_for_approval":
            hold = True
            notes.append(f"policy: {cls} needs approval")
    return list(dict.fromkeys(kept)), hold, list(dict.fromkeys(notes))


def view(tenant) -> dict:
    current, base = get(tenant), defaults(tenant)
    return {"modes": current, "defaults": base, "classes": [{"key": k, "label": v} for k, v in ACTION_CLASSES.items()],
            "mode_options": list(MODES)}


def update(db: Session, tenant, actor_id: str, modes: dict) -> dict:
    """Apply the owner's change and audit it. Unknown classes or modes raise ValueError. The caller commits."""
    bad = [k for k in modes if k not in ACTION_CLASSES] + [f"{k}={v}" for k, v in modes.items() if v not in MODES]
    if bad:
        raise ValueError(f"unknown action class or mode: {', '.join(bad)}")
    current = get(tenant)
    changes = {k: {"from": current[k], "to": v} for k, v in modes.items() if current[k] != v}
    if changes:
        stored = dict(_raw(tenant))
        stored["modes"] = {**(stored.get("modes") if isinstance(stored.get("modes"), dict) else {}),
                           **{k: c["to"] for k, c in changes.items()}}
        cfg = dict(tenant.brand_config or {})
        cfg[KEY] = stored
        tenant.brand_config = cfg
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="ai.agent_policy_changed", target_type="tenant",
                     target_id=tenant.id, payload={"changes": changes})
    return changes
