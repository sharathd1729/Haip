"""Invoice details settings: the seller profile (brand_config.invoice_profile), payment automation switches
(brand_config.payments) and the logo printed on invoices.

Logo: an uploaded one (re-encoded to PNG with Pillow, stored via media_storage) wins; otherwise the Branding page's
logo is reused when it is an uploaded image (a data: URL). An http(s) branding logo is never fetched: no outbound calls.
"""
from __future__ import annotations

import io
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.tenant import Tenant
from app.schemas.invoice import GST_STATES, InvoiceProfile, InvoiceSettingsIn, PaymentAutomation
from app.services import invoice_pdf, media_storage
from app.services.invoice_service import get_profile

log = structlog.get_logger()

_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


class LogoError(ValueError):
    """An upload the user has to fix; the message is safe to show."""


def payment_automation(tenant: Tenant) -> PaymentAutomation:
    raw = (tenant.brand_config or {}).get("payments") or {}
    try:
        return PaymentAutomation(**raw)
    except ValueError:
        return PaymentAutomation()


def _branding_logo(tenant: Tenant) -> Optional[str]:
    return ((tenant.brand_config or {}).get("branding_theme") or {}).get("logoUrl")


def logo_source(tenant: Tenant, profile: Optional[InvoiceProfile] = None) -> Optional[str]:
    profile = profile or get_profile(tenant)
    if profile.logo_key:
        return "uploaded"
    if profile.use_branding_logo and invoice_pdf.logo_from_data_url(_branding_logo(tenant)):
        return "branding"
    return None


def logo_bytes(tenant: Tenant) -> Optional[bytes]:
    """The logo to print, or None. A storage error only drops the logo; the invoice still renders."""
    profile = get_profile(tenant)
    if profile.logo_key:
        try:
            return media_storage.download_media(profile.logo_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("invoice_logo_download_failed", tenant_id=tenant.id, error=str(exc))
            return None
    if profile.use_branding_logo:
        return invoice_pdf.logo_from_data_url(_branding_logo(tenant))
    return None


def settings_out(tenant: Tenant) -> dict:
    profile = get_profile(tenant)
    source = logo_source(tenant, profile)
    url = None
    if source == "uploaded":
        url = media_storage.get_presigned_media_url(profile.logo_key, expires_in=900)
    elif source == "branding":
        url = _branding_logo(tenant)
    return {"profile": profile.model_dump(), "payments": payment_automation(tenant).model_dump(),
            "logo_url": url, "logo_source": source, "missing": profile.missing_for_invoice(), "states": GST_STATES}


def save_settings(db: Session, tenant: Tenant, body: InvoiceSettingsIn, actor_id: str) -> dict:
    cfg = dict(tenant.brand_config or {})
    before = cfg.get("invoice_profile") or {}
    profile = body.profile.model_dump()
    # The logo is changed only through the logo endpoints; a settings save keeps whatever is stored.
    profile["logo_key"] = before.get("logo_key")
    cfg["invoice_profile"] = profile
    changes = {k: {"from": before.get(k), "to": v} for k, v in profile.items() if before.get(k) != v}
    if body.payments is not None:
        prev = cfg.get("payments") or {}
        cfg["payments"] = {**prev, **body.payments.model_dump()}
        if prev.get("auto_balance_reminder", False) != body.payments.auto_balance_reminder:
            changes["auto_balance_reminder"] = {"from": prev.get("auto_balance_reminder", False),
                                                "to": body.payments.auto_balance_reminder}
    tenant.brand_config = cfg
    append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="settings.invoice_profile_updated",
                 target_type="tenant", target_id=tenant.id, payload={"changes": changes})
    db.commit()
    db.refresh(tenant)
    return settings_out(tenant)


def reencode_logo(content: bytes, content_type: str) -> bytes:
    """Validate and re-encode an uploaded logo to a PNG at most 1200 x 480 px."""
    if not content:
        raise LogoError("The file is empty.")
    if len(content) > MAX_LOGO_BYTES:
        raise LogoError("The logo is larger than 2 MB. Use a smaller PNG or JPG.")
    if (content_type or "").split(";")[0].strip().lower() not in _LOGO_TYPES:
        raise LogoError("Use a PNG, JPG or WebP image for the logo.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise LogoError("Use a PNG, JPG or WebP image for the logo.")
            if im.width * im.height > 25_000_000:
                raise LogoError("That image is too large. Use one under 5000 x 5000 pixels.")
            im.load()
            im = im.convert("RGBA")
            im.thumbnail((1200, 480))
            out = io.BytesIO()
            im.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except LogoError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LogoError("That file could not be read as an image.") from exc


def save_logo(db: Session, tenant: Tenant, content: bytes, content_type: str, actor_id: str) -> dict:
    png = reencode_logo(content, content_type)
    key = media_storage.upload_invoice_logo(tenant.id, png)
    cfg = dict(tenant.brand_config or {})
    profile = dict(cfg.get("invoice_profile") or {})
    old = profile.get("logo_key")
    profile["logo_key"] = key
    cfg["invoice_profile"] = profile
    tenant.brand_config = cfg
    append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="settings.invoice_logo_uploaded",
                 target_type="tenant", target_id=tenant.id, payload={"bytes": len(png), "replaced": bool(old)})
    db.commit()
    db.refresh(tenant)
    return settings_out(tenant)


def remove_logo(db: Session, tenant: Tenant, actor_id: str) -> dict:
    cfg = dict(tenant.brand_config or {})
    profile = dict(cfg.get("invoice_profile") or {})
    if profile.get("logo_key"):
        profile["logo_key"] = None
        cfg["invoice_profile"] = profile
        tenant.brand_config = cfg
        append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="settings.invoice_logo_removed",
                     target_type="tenant", target_id=tenant.id, payload={})
        db.commit()
        db.refresh(tenant)
    return settings_out(tenant)
