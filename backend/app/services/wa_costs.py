"""WhatsApp message cost (WhatsApp step 2): Meta's status webhooks carry a ``pricing`` object (category, billable)
for every business message. One row per wamid is kept (wa_pricing_events); cost = billable messages x the
workspace's rate for that category (brand_config.marketing_studio.whatsapp_rates_inr, owner-set, default
marketing 0.86 / utility 0.12 / authentication 0.12 rupees). Service replies and messages after a free entry point
(click-to-WhatsApp ads, ``referral_conversion``) are not billable, so they cost nothing.

These are estimates in the workspace's own rates: Meta's invoice is the final word.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.wa_pricing_event import WaPricingEvent


def record(db: Session, tenant_id: str, status_obj: dict) -> bool:
    """Keep the pricing of one status callback (first one per message wins). True when a row was written."""
    pricing = status_obj.get("pricing")
    wamid = status_obj.get("id")
    if not isinstance(pricing, dict) or not wamid:
        return False
    if db.query(WaPricingEvent.id).filter_by(tenant_id=tenant_id, wamid=wamid).first():
        return False
    try:
        ts = datetime.fromtimestamp(int(status_obj.get("timestamp")), tz=UTC)
    except (TypeError, ValueError):
        ts = datetime.now(UTC)
    try:
        with db.begin_nested():
            db.add(WaPricingEvent(tenant_id=tenant_id, wamid=str(wamid)[:255],
                                  category=str(pricing.get("category") or "")[:40].lower() or None,
                                  billable=bool(pricing.get("billable", True)),
                                  pricing_model=str(pricing.get("pricing_model") or "")[:20] or None, occurred_at=ts))
    except IntegrityError:  # the same message's next status arrived at the same moment
        return False
    return True


def rates(tenant) -> dict[str, float]:
    from app.services.marketing_whatsapp import settings_of

    return settings_of(tenant)["rates_inr"]


def cost_of(db: Session, tenant, wamids: list[str]) -> dict:
    """{"messages": billable count, "amount_inr": estimate, "by_category": {...}} for these messages."""
    out = {"messages": 0, "amount_inr": 0.0, "by_category": {}}
    if not wamids:
        return out
    table = rates(tenant)
    rows = (
        db.query(WaPricingEvent.category, WaPricingEvent.billable)
        .filter(WaPricingEvent.tenant_id == tenant.id, WaPricingEvent.wamid.in_(wamids))
        .all()
    )
    for category, billable in rows:
        if not billable:
            continue
        cat = (category or "").upper()
        amount = table.get(cat, 0.0)
        bucket = out["by_category"].setdefault(cat.lower() or "unknown", {"messages": 0, "amount_inr": 0.0})
        bucket["messages"] += 1
        bucket["amount_inr"] = round(bucket["amount_inr"] + amount, 2)
        out["messages"] += 1
        out["amount_inr"] = round(out["amount_inr"] + amount, 2)
    return out


def period_cost(db: Session, tenant, start: datetime, end: datetime) -> dict:
    """All business messages priced in a window (campaigns, automations, inbox templates)."""
    wamids = [w for (w,) in db.query(WaPricingEvent.wamid).filter(
        WaPricingEvent.tenant_id == tenant.id, WaPricingEvent.occurred_at >= start, WaPricingEvent.occurred_at <= end)]
    return cost_of(db, tenant, wamids)
