"""WhatsApp campaigns from the agency (agency M3), on top of the existing campaigns module (endpoints/messaging.py).

The agency never sends. It creates a DRAFT campaign (WACampaign, status draft) for an APPROVED promo, with the
workspace's approved Meta template and an audience, and shows the cost before anyone launches it. Launching stays in
WhatsApp > Campaigns (owner/manager), unchanged.

  * Audiences: the opted-in subscriber list (tags) for automatic drafts. A CRM-leads audience needs the person
    creating the draft to confirm consent, every time (wa_lead_audience.prepare_audience_filter), so the agency
    never picks one on its own.
  * Cost: audience size x a per-message rate by template category. Rates are the workspace's own (owner setting,
    brand_config.marketing_studio.whatsapp_rates_inr), defaulting to DEFAULT_RATES_INR. They are an estimate: Meta's
    invoice is the truth.
  * Automatic draft: when a promo whose targets include "whatsapp" is approved and the owner has set a default
    template + subscriber tags (brand_config.marketing_studio.whatsapp).
"""
from typing import Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.tenant import Tenant
from app.services import marketing_content_service as content_svc
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

SETTINGS_KEY = "marketing_studio"
# Per-message estimate for India (INR), by template category. Owners set their own from their Meta invoice.
DEFAULT_RATES_INR = {"MARKETING": 0.86, "UTILITY": 0.12, "AUTHENTICATION": 0.12}
MAX_RATE = 20.0


def _section(tenant: Tenant) -> dict:
    cfg = (tenant.brand_config or {}).get(SETTINGS_KEY) if tenant is not None else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def settings_of(tenant: Tenant) -> dict:
    sec = _section(tenant)
    rates = {**DEFAULT_RATES_INR, **{k: float(v) for k, v in (sec.get("whatsapp_rates_inr") or {}).items()
                                     if k in DEFAULT_RATES_INR and isinstance(v, (int, float)) and 0 <= v <= MAX_RATE}}
    auto = sec.get("whatsapp") if isinstance(sec.get("whatsapp"), dict) else {}
    return {"rates_inr": rates, "template_id": auto.get("template_id"), "tags": list(auto.get("tags") or []),
            "variable_map": auto.get("variable_map") or {}}


def update_settings(db: Session, tenant: Tenant, actor_id: str, *, rates: Optional[dict] = None,
                    template_id: Optional[str] = None, tags: Optional[list] = None,
                    variable_map: Optional[dict] = None) -> dict:
    before = settings_of(tenant)
    sec = _section(tenant)
    if rates is not None:
        for k, v in rates.items():
            if k not in DEFAULT_RATES_INR or not isinstance(v, (int, float)) or not 0 <= v <= MAX_RATE:
                raise MarketingError(422, "bad_rate", f"Rates are rupees per message, 0 to {MAX_RATE:g}.")
        sec["whatsapp_rates_inr"] = {k: float(v) for k, v in rates.items()}
    if template_id is not None or tags is not None or variable_map is not None:
        auto = dict(sec.get("whatsapp") or {})
        if template_id is not None:
            auto["template_id"] = template_id or None
        if tags is not None:
            auto["tags"] = [str(t)[:50] for t in tags][:10]
        if variable_map is not None:
            auto["variable_map"] = variable_map
        sec["whatsapp"] = auto
    cfg = dict(tenant.brand_config or {})
    cfg[SETTINGS_KEY] = sec
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.whatsapp.settings", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": settings_of(tenant)})
    return settings_of(tenant)


def _template(db: Session, tenant_id: str, template_id: Optional[str]):
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=tenant_id).first() if template_id else None
    if tmpl is None:
        raise MarketingError(404, "template_not_found", "Choose one of this workspace's WhatsApp templates.")
    if tmpl.status != TemplateStatus.APPROVED:
        raise MarketingError(422, "template_not_approved", "Meta has not approved this template yet.")
    return tmpl


def _category(tmpl) -> str:
    cat = getattr(tmpl.category, "value", tmpl.category) or "MARKETING"
    return str(cat).upper()


def estimate(db: Session, tenant: Tenant, template_id: str, audience_filter: Optional[dict]) -> dict:
    """Who would get it and what it would cost, before anything is created or sent."""
    from app.services import wa_lead_audience
    from app.services.wa_campaign_delivery import audience_members
    tmpl = _template(db, tenant.id, template_id)
    try:
        prepared = wa_lead_audience.prepare_audience_filter(audience_filter or {})
    except wa_lead_audience.AudienceError as exc:
        raise MarketingError(422, "consent_required", str(exc))
    people = audience_members(db, tenant.id, prepared)
    rate = settings_of(tenant)["rates_inr"].get(_category(tmpl), DEFAULT_RATES_INR["MARKETING"])
    return {"recipients": len(people), "category": _category(tmpl), "rate_inr": rate,
            "total_inr": round(len(people) * rate, 2), "template": tmpl.name,
            "note": "Estimate from your per-message rates; Meta's invoice is the final amount."}


def draft_campaign(db: Session, tenant: Tenant, item_id: str, actor_id: Optional[str], *, template_id: str,
                   audience_filter: Optional[dict], variable_map: Optional[dict]):
    """A DRAFT WhatsApp campaign for an approved promo. Never launched here."""
    from app.api.v1.endpoints.messaging import CampaignStatus, WACampaign
    from app.services import wa_lead_audience
    from app.services import wa_template_service as wts
    item = content_svc.get_item(db, tenant.id, item_id)
    if item.kind != "promo":
        raise MarketingError(422, "not_a_promo", "WhatsApp campaigns are made from promos.")
    if item.status not in ("approved", "scheduled", "published"):
        raise MarketingError(409, "not_approved", "Approve the promo first.")
    tmpl = _template(db, tenant.id, template_id)
    missing = wts.unmapped_variables(tmpl.components, variable_map)
    if missing:
        raise MarketingError(422, "variables_unmapped", f"Say what to fill in for: {', '.join(missing)}.")
    try:
        prepared = wa_lead_audience.prepare_audience_filter(audience_filter or {})
    except wa_lead_audience.AudienceError as exc:
        raise MarketingError(422, "consent_required", str(exc))
    cost = estimate(db, tenant, template_id, prepared)
    campaign = WACampaign(tenant_id=tenant.id, name=f"Studio: {item.title}"[:255], template_id=tmpl.id,
                          audience_filter=prepared, variable_map=variable_map or {}, status=CampaignStatus.DRAFT)
    db.add(campaign)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.whatsapp.drafted", actor_user_id=actor_id or "agency",
                 target_type="wa_campaign", target_id=campaign.id,
                 payload={"content_id": item.id, "template": tmpl.name, "recipients": cost["recipients"],
                          "estimate_inr": cost["total_inr"], "audience": {k: v for k, v in prepared.items() if k != "consent_confirmed"}})
    return campaign, cost


def on_approved(db: Session, tenant: Tenant, item) -> Optional[dict]:
    """Automatic draft for an approved promo targeting WhatsApp, with the owner's defaults (subscriber tags only)."""
    from app.services.marketing_channels import targets_of
    if item.kind != "promo" or "whatsapp" not in targets_of(item):
        return None
    s = settings_of(tenant)
    if not s["template_id"]:
        return {"skipped": "Choose a default WhatsApp template in Studio settings to draft campaigns automatically."}
    try:
        campaign, cost = draft_campaign(db, tenant, item.id, None, template_id=s["template_id"],
                                        audience_filter={"tags": s["tags"]} if s["tags"] else {},
                                        variable_map=s["variable_map"])
    except MarketingError as exc:
        log.info("whatsapp_auto_draft_skipped", tenant_id=tenant.id, item_id=item.id, reason=exc.message)
        return {"skipped": exc.message}
    return {"campaign_id": campaign.id, **cost}


def studio_campaigns(db: Session, tenant_id: str, limit: int = 20) -> list[dict]:
    from app.api.v1.endpoints.messaging import WACampaign
    rows = (db.query(WACampaign).filter(WACampaign.tenant_id == tenant_id, WACampaign.name.like("Studio: %"))
            .order_by(WACampaign.created_at.desc()).limit(limit).all())
    return [{"id": c.id, "name": c.name, "status": getattr(c.status, "value", c.status), "sent": c.sent_count,
             "delivered": c.delivered_count, "created_at": c.created_at} for c in rows]
