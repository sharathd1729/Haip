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


# ── Suggestion: "Fill from my website / logo" (no AI; the owner reviews, then saves) ────────────────────────────────

# The HAIP site builder's theme packs: (colour a, colour b, display face). Mirrors frontend/src/site-blocks/packs.ts
# (a, b, display); change both together. Every pack's display face is a serif.
SITE_PACKS = {
    "goa": ("#1F7FC4", "#A6D23C", "serif"), "kerala": ("#1F6B45", "#D9A630", "serif"),
    "rajasthan": ("#B23A6B", "#2E4A9A", "serif"), "malnad": ("#3E6A3A", "#9B5B2E", "serif"),
    "himalaya": ("#3B5B7A", "#E79A55", "serif"), "chettinad": ("#A13E25", "#D6A237", "serif"),
}
MIN_CONTRAST = 3.0          # WCAG AA for large text / UI parts: headlines and the CTA pill sit on these colours


def _rgb(hex_: str) -> tuple[int, int, int]:
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def _luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_on_white(hex_: str) -> float:
    return 1.05 / (_luminance(_rgb(hex_)) + 0.05)


def readable(hex_: str) -> str:
    """The colour, darkened in small steps until white text on it (and it on white) reaches MIN_CONTRAST."""
    rgb = _rgb(hex_)
    for _ in range(40):
        if contrast_on_white(_hex(rgb)) >= MIN_CONTRAST:
            break
        rgb = tuple(c * 0.92 for c in rgb)
    return _hex(rgb)


def logo_palette(raw: bytes, n: int = 2) -> list[str]:
    """Up to n dominant non-neutral colours of an image, most frequent first; the second is the one most unlike the
    first among the rest. Transparent, near-white, near-black and grey pixels are ignored."""
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img.thumbnail((160, 160))
    px = [(r, g, b) for r, g, b, a in img.getdata()
          if a >= 128 and max(r, g, b) - min(r, g, b) >= 40 and max(r, g, b) >= 40 and min(r, g, b) <= 225]
    if len(px) < 20:
        return []
    strip = Image.new("RGB", (len(px), 1))
    strip.putdata(px)
    q = strip.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors(), reverse=True)                          # [(count, index)], most frequent first
    colours = [tuple(pal[i * 3:i * 3 + 3]) for c, i in counts if c >= 0.03 * len(px)]
    if not colours:
        return []
    first, rest = colours[0], colours[1:]
    out = [first]
    if rest and n > 1:
        out.append(max(rest, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, first))))
    return [_hex(c) for c in out]


def _site_pack(db: Session, tenant_id: str) -> Optional[str]:
    from app.models.website import Site, SiteVersion

    site = db.query(Site).filter_by(tenant_id=tenant_id).first()
    vid = site and (site.live_version_id or site.draft_version_id)
    ver = db.query(SiteVersion).filter_by(id=vid, tenant_id=tenant_id).first() if vid else None
    pack = ((ver.doc or {}).get("theme") or {}).get("pack") if ver is not None else None
    return pack if pack in SITE_PACKS else None


def suggest(db: Session, tenant: Tenant, logo_asset_id: Optional[str] = None, read_bytes=None) -> dict:
    """Brand + accent colour (and typeface for a website) suggested from the HAIP-built website's theme, else from
    the logo (the one given, else the saved one). Never saved here: the owner reviews it in the form and saves."""
    from app.services import media_library_service as library

    current = get_kit(tenant)
    pack = _site_pack(db, tenant.id)
    if pack:
        a, b, font = SITE_PACKS[pack]
        return {"source": "website", "primary": readable(a), "accent": readable(b), "font": font}
    asset_id = logo_asset_id or current["logo_asset_id"]
    logo = db.query(MediaAsset).filter_by(id=asset_id, tenant_id=tenant.id, status="active").first() if asset_id else None
    if logo is None or not (logo.mime_type or "").startswith("image/"):
        raise content_svc.MarketingError(422, "nothing_to_read", "Build your website in HAIP or pick a logo image first.")
    try:
        colours = logo_palette((read_bytes or library._read_object)(logo.storage_key))
    except Exception as exc:  # noqa: BLE001 -- unreadable file or storage outage: say so, never guess
        raise content_svc.MarketingError(422, "logo_unreadable", "The logo could not be read.", [str(exc)[:200]])
    if not colours:
        raise content_svc.MarketingError(422, "no_colours", "The logo has no clear colours (only white, black or grey).")
    return {"source": "logo", "primary": readable(colours[0]),
            "accent": readable(colours[1]) if len(colours) > 1 else current["accent"], "font": current["font"]}
