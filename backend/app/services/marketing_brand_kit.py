"""Brand kit (agency M3): the logo, colours and typeface every rendered post uses.

Stored in brand_config.marketing_studio.brand_kit. The kit is FROZEN into each draft's payload.design when photos are
attached (marketing_photos.fill), so an approval covers the exact look; changing the kit later never alters a post
that is already approved. The logo is an active library image (PNG keeps its transparency) and is kept out of the
photo picker.
"""
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.schemas.marketing import BrandKit
from app.services import marketing_content_service as content_svc
from app.services.media_library_service import _panel_colour

KEY = "brand_kit"


def get_kit(tenant: Optional[Tenant]) -> dict:
    section = ((tenant.brand_config or {}).get("marketing_studio") or {}) if tenant is not None else {}
    raw = section.get(KEY) if isinstance(section, dict) else None
    try:
        return BrandKit.model_validate(raw or {}).model_dump()
    except ValueError:
        return BrandKit().model_dump()


def logo_id(tenant: Optional[Tenant]) -> Optional[str]:
    return get_kit(tenant).get("logo_asset_id")


def put_kit(db: Session, tenant: Tenant, data: dict, actor_id: str) -> dict:
    try:
        kit = BrandKit.model_validate(data).model_dump()
    except ValueError as exc:
        raise content_svc.MarketingError(422, "bad_brand_kit", "Check the brand kit fields.", [str(exc)[:300]])
    if kit["logo_asset_id"]:
        logo = db.query(MediaAsset).filter_by(id=kit["logo_asset_id"], tenant_id=tenant.id, status="active").first()
        if logo is None or logo.mime_type not in ("image/png", "image/jpeg", "image/webp"):
            raise content_svc.MarketingError(422, "logo_unavailable", "Pick an image from the library as the logo.")
    before = get_kit(tenant)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    section[KEY] = kit
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.brand_kit.updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": kit})
    return kit


def design_defaults(tenant: Tenant) -> dict:
    """What a draft's design takes from the kit when it is first filled. Keys the draft already has are kept."""
    kit = get_kit(tenant)
    return {"colour": kit["primary"] or _panel_colour(tenant), "accent": kit["accent"], "font": kit["font"],
            "logo_asset_id": kit["logo_asset_id"],
            "logo_position": kit["logo_position"] if kit["logo_asset_id"] else "none"}
