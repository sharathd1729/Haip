"""The two owner switches behind the AI sales agent, stored in ``tenants.brand_config`` (no migration needed):

  price_disclosure     "handoff" (default: the AI never states a price) | "grounded" (only figures the package price engine
                       computed for this guest's dates, party and route)               -- read by price_policy.price_mode()
  sales_agent.mode     "off" (default: today's behaviour, nothing below runs) | "suggest" | "autopilot"

  off        the concierge works exactly as before.
  suggest    the concierge reads availability from the booking calendar for every message with dates (with the nearest free
             dates when they are taken), and, in grounded price mode, prepares a quote on the lead and puts a pending
             "send quote + payment link" action in front of staff. Nothing is sent without a person.
  autopilot  as suggest, but the agent sends the quote + payment link itself when every guard passes; otherwise it falls
             back to suggest for that lead.

Only the owner may change either (the endpoint enforces it); every change is a chained audit row with before/after values.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.services.price_policy import PRICE_MODES, price_mode

MODES = ("off", "suggest", "autopilot")


def mode(tenant) -> str:
    """The tenant's sales agent mode; anything unrecognised is "off"."""
    cfg = getattr(tenant, "brand_config", None) or {}
    sa = cfg.get("sales_agent") if isinstance(cfg, dict) else None
    value = sa.get("mode") if isinstance(sa, dict) else None
    return value if value in MODES else "off"


def readiness(db: Session, tenant) -> dict:
    """What the switches depend on, so the owner sees why the agent would hold a quote back. Read-only."""
    from app.models.integration import Integration
    from app.services import business_data_service as bds
    from app.services.quote_send_service import template_status
    packages = bds.list_effective(db, tenant.id, "package")
    auto = [r.key for r in packages if bds.parse(r).auto_bookable]
    auto += [r.key for r in bds.list_effective(db, tenant.id, "destination") if bds.parse(r).auto_bookable]
    rzp = db.query(Integration.id).filter(Integration.tenant_id == tenant.id, Integration.kind == "razorpay",
                                          Integration.status == "active", Integration.credentials_kms_blob.isnot(None)).first()
    return {"published_packages": len(packages), "auto_bookable": sorted(auto), "razorpay_connected": rzp is not None,
            "quote_template_status": template_status(db, tenant.id)}


def view(db: Session, tenant) -> dict:
    return {"price_disclosure": price_mode(tenant), "sales_agent_mode": mode(tenant), "readiness": readiness(db, tenant)}


def update(db: Session, tenant, actor_id: str, price_disclosure: Optional[str] = None, sales_agent_mode: Optional[str] = None) -> dict:
    """Apply the owner's change and audit it. Returns {field: {from, to}} for what changed. The caller commits."""
    if price_disclosure is not None and price_disclosure not in PRICE_MODES:
        raise ValueError(f"price_disclosure must be one of {', '.join(PRICE_MODES)}")
    if sales_agent_mode is not None and sales_agent_mode not in MODES:
        raise ValueError(f"sales_agent_mode must be one of {', '.join(MODES)}")
    cfg = dict(tenant.brand_config or {})
    changes: dict = {}
    if price_disclosure is not None and price_mode(tenant) != price_disclosure:
        changes["price_disclosure"] = {"from": price_mode(tenant), "to": price_disclosure}
        cfg["price_disclosure"] = price_disclosure
    if sales_agent_mode is not None and mode(tenant) != sales_agent_mode:
        changes["sales_agent_mode"] = {"from": mode(tenant), "to": sales_agent_mode}
        cfg["sales_agent"] = {**(cfg.get("sales_agent") if isinstance(cfg.get("sales_agent"), dict) else {}), "mode": sales_agent_mode}
    if changes:
        tenant.brand_config = cfg                       # a new dict: JSON columns do not track in-place mutation
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="ai.sales_settings_changed",
                     target_type="tenant", target_id=tenant.id, payload={"changes": changes})
    return changes
