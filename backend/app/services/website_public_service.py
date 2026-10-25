"""What a guest's browser (through the sites renderer) may read: the live document plus live HAIP data.

Host -> site uses website_host_lookup() (SECURITY DEFINER, migration 158) on PostgreSQL, so the lookup needs no tenant
context; every read after it sets app.tenant_id and goes through RLS. Only public fields leave this module: no guest
data, no staff names, no internal notes, prices only when the site shows them.
"""
import base64
import hashlib
import hmac
import json
import time
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.database import set_tenant_context
from app.models.media_asset import MediaAsset
from app.models.property import Property, PropertyAddOn
from app.models.tenant import Tenant
from app.models.website import Site, SiteDomain, SitePageView, SiteVersion
from app.services import website_blocks as wb
from app.services import website_pricing as pricing
from app.services.website_service import WebsiteError, bookable_properties, site_settings

PREVIEW_TTL = 60 * 60 * 24


def normalise_host(host: str) -> str:
    return (host or "").strip().lower().split(":")[0].rstrip(".")


def resolve_host(db: Session, host: str) -> tuple[Tenant, Site]:
    h = normalise_host(host)
    if not h or len(h) > 253:
        raise WebsiteError(404, "site_not_found", "No website here.")
    if db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT site_id, tenant_id FROM website_host_lookup(:h)"), {"h": h}).first()
        site_id, tenant_id = (row[0], row[1]) if row else (None, None)
    else:
        d = db.query(SiteDomain).filter(SiteDomain.hostname == h, SiteDomain.status.in_(("verified", "active"))).first()
        site_id, tenant_id = (d.site_id, d.tenant_id) if d else (None, None)
    if not site_id:
        raise WebsiteError(404, "site_not_found", "No website here.")
    set_tenant_context(db, tenant_id)
    tenant = db.query(Tenant).filter_by(id=tenant_id, is_active=True).first()
    site = db.query(Site).filter_by(id=site_id, tenant_id=tenant_id).first()
    if not tenant or not site:
        raise WebsiteError(404, "site_not_found", "No website here.")
    return tenant, site


def require_live(db: Session, site: Site) -> SiteVersion:
    if site.status != "live" or not site.live_version_id:
        raise WebsiteError(404, "site_not_live", "This website isn't published yet.")
    v = db.get(SiteVersion, site.live_version_id)
    if not v:
        raise WebsiteError(404, "site_not_live", "This website isn't published yet.")
    return v


# ─── preview links (drafts, signed) ─────────────────────────────────────────────────────────────────────

def _secret() -> bytes:
    return (app_settings.SECRET_KEY + ":website-preview").encode("utf-8")


def preview_token(site: Site, version: SiteVersion, ttl: int = PREVIEW_TTL) -> str:
    body = json.dumps({"s": site.id, "t": site.tenant_id, "v": version.id, "e": int(time.time()) + ttl}, separators=(",", ":"))
    b = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{b}.{sig}"


def read_preview(db: Session, token: str) -> tuple[Tenant, Site, SiteVersion]:
    try:
        b, sig = token.split(".", 1)
        good = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(good, sig):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
        if int(data["e"]) < time.time():
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise WebsiteError(404, "preview_expired", "This preview link has expired.")
    set_tenant_context(db, data["t"])
    tenant = db.get(Tenant, data["t"])
    site = db.query(Site).filter_by(id=data["s"], tenant_id=data["t"]).first()
    v = db.query(SiteVersion).filter_by(id=data["v"], site_id=data["s"], tenant_id=data["t"]).first()
    if not tenant or not site or not v:
        raise WebsiteError(404, "preview_expired", "This preview link has expired.")
    return tenant, site, v


# ─── live data ──────────────────────────────────────────────────────────────────────────────────────────

def _photos(prop: Property) -> list[str]:
    out = []
    for p in prop.photos if isinstance(prop.photos, list) else []:
        url = p.get("url") or p.get("large") or p.get("original") if isinstance(p, dict) else p
        if isinstance(url, str) and url.startswith("https://"):
            out.append(url[:1000])
    return out[:20]


def stay_slug(prop: Property) -> str:
    from app.services.website_service import slugify
    return slugify(prop.slug or prop.name)


def property_out(db: Session, prop: Property, *, show_prices: bool, today: date, detail: bool = False) -> dict:
    out = {
        "id": prop.id, "slug": stay_slug(prop), "name": prop.name, "type": prop.type or "",
        "sleeps": int(prop.max_adults or 0) + int(prop.max_children or 0), "max_adults": int(prop.max_adults or 0),
        "bedrooms": prop.bedrooms, "bathrooms": prop.bathrooms, "city": prop.city or "",
        "photos": _photos(prop), "amenities": [str(a)[:60] for a in (prop.amenities or []) if isinstance(a, str)][:30],
        "summary": (prop.description or "")[:280],
    }
    if show_prices:
        fp = pricing.from_price(db, prop, today)
        out["from_price"] = str(fp) if fp is not None else None
    if detail:
        out["description"] = (prop.description or "")[:4000]
        out["faqs"] = [{"q": str(f.get("q") or f.get("question") or "")[:200], "a": str(f.get("a") or f.get("answer") or "")[:1000]}
                       for f in (prop.faqs or []) if isinstance(f, dict)][:12]
        out["extras"] = [{"id": a.id, "name": a.name, "description": (a.description or "")[:300], "category": a.category,
                          "price": str(a.price) if show_prices else None, "price_type": a.price_type}
                         for a in db.query(PropertyAddOn).filter_by(tenant_id=prop.tenant_id, property_id=prop.id, is_active=True)
                         .order_by(PropertyAddOn.sort_order).all()]
        out["lat"] = float(prop.lat) if prop.lat is not None else None
        out["lng"] = float(prop.lng) if prop.lng is not None else None
        out["address"] = (prop.address or "")[:300]
    return out


def _policies(db: Session, tenant: Tenant) -> dict:
    from app.services import business_data_service as bds
    out: dict = {}
    for kind in ("cancellation_policy", "payment_policy", "stay_rules"):
        try:
            rec = bds.get_effective(db, tenant.id, kind, "default")
        except Exception:  # noqa: BLE001 -- a broken record hides that section instead of breaking the site
            rec = None
        if rec and isinstance(rec.data, dict):
            out[kind] = {k: v for k, v in rec.data.items() if k not in ("confirmed_by_ratha", "approver_roles")}
    return out


def _legal(tenant: Tenant) -> dict:
    from app.services.invoice_service import get_profile
    p = get_profile(tenant)
    return {"legal_name": p.legal_name or tenant.name, "gstin": p.gstin, "address": p.address}


def asset_urls(db: Session, tenant_id: str, doc: dict, extra: Optional[set] = None) -> dict:
    """asset id -> a path the renderer proxies (/_haip/media/<id>); real storage URLs are signed per request.
    `extra` = photos a v2 page binds from the library (hero, gallery) on top of the ones the doc names."""
    ids = wb.asset_ids(doc) | set(extra or ())
    if not ids:
        return {}
    rows = db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(list(ids)),
                                       MediaAsset.status == "active").all()
    return {a.id: {"src": f"/_haip/media/{a.id}", "alt": (a.alt_text or "")[:200], "w": a.width, "h": a.height} for a in rows}


def bootstrap(db: Session, tenant: Tenant, site: Site, version: SiteVersion, *, preview: bool = False) -> dict:
    from app.services import website_spec_service as wspec
    from app.services.business_data_service import tenant_today
    if wspec.is_v2(version.doc):
        return wspec.bootstrap(db, tenant, site, version, preview=preview)
    cfg = site_settings(site)
    today = tenant_today(db, tenant.id)
    props = bookable_properties(db, tenant.id, cfg.property_ids or None)
    return {
        "site": {"id": site.id, "name": site.name, "status": site.status, "preview": preview,
                 "booking_mode": cfg.booking_mode, "deposit_percent": cfg.deposit_percent, "show_prices": cfg.show_prices,
                 "hold_minutes": cfg.hold_minutes, "min_nights": cfg.min_nights, "prices_include_gst": cfg.prices_include_gst,
                 "today": today.isoformat()},
        "version": {"id": version.id, "number": version.number, "sha256": version.sha256},
        "doc": version.doc,
        "stays": [property_out(db, p, show_prices=cfg.show_prices, today=today) for p in props],
        "assets": asset_urls(db, tenant.id, version.doc),
        "policies": _policies(db, tenant),
        "legal": _legal(tenant),
    }


def stay_detail(db: Session, tenant: Tenant, site: Site, slug: str) -> dict:
    from app.services.business_data_service import tenant_today
    cfg = site_settings(site)
    for p in bookable_properties(db, tenant.id, cfg.property_ids or None):
        if stay_slug(p) == slug:
            return property_out(db, p, show_prices=cfg.show_prices, today=tenant_today(db, tenant.id), detail=True)
    raise WebsiteError(404, "stay_not_found", "That stay isn't on this website.")


def media_url(db: Session, tenant_id: str, doc: dict, asset_id: str) -> str:
    from app.services import website_spec_service as wspec
    from app.services.media_storage import get_presigned_media_url
    allowed = wb.asset_ids(doc)
    if asset_id not in allowed and wspec.is_v2(doc):
        allowed = allowed | wspec.media_ids(db, db.get(Tenant, tenant_id), doc)
    if asset_id not in allowed:
        raise WebsiteError(404, "not_found", "Not found")
    a = db.query(MediaAsset).filter_by(id=asset_id, tenant_id=tenant_id, status="active").first()
    url = get_presigned_media_url(a.storage_key, expires_in=3600) if a else None
    if not url:
        raise WebsiteError(404, "not_found", "Not found")
    return url


def record_view(db: Session, tenant_id: str, site_id: str, path: str, source: Optional[str], today: date) -> None:
    p = (path or "/").split("?")[0][:200] or "/"
    src = (source or "direct").strip().lower()[:60] or "direct"
    day = today.isoformat()
    n = db.query(SitePageView).filter_by(site_id=site_id, day=day, path=p, source=src).update(
        {"views": SitePageView.views + 1}, synchronize_session=False)
    if n == 0:
        try:
            with db.begin_nested():
                db.add(SitePageView(tenant_id=tenant_id, site_id=site_id, day=day, path=p, source=src, views=1))
        except IntegrityError:
            db.query(SitePageView).filter_by(site_id=site_id, day=day, path=p, source=src).update(
                {"views": SitePageView.views + 1}, synchronize_session=False)


def views_summary(db: Session, site: Site, today: date, days: int = 30) -> dict:
    since = (today - timedelta(days=days - 1)).isoformat()
    rows = db.query(SitePageView).filter(SitePageView.site_id == site.id, SitePageView.tenant_id == site.tenant_id,
                                         SitePageView.day >= since).all()
    by_day: dict = {}
    by_path: dict = {}
    by_source: dict = {}
    for r in rows:
        by_day[r.day] = by_day.get(r.day, 0) + r.views
        by_path[r.path] = by_path.get(r.path, 0) + r.views
        by_source[r.source] = by_source.get(r.source, 0) + r.views
    return {"days": days, "total": sum(by_day.values()), "by_day": sorted(by_day.items()),
            "top_pages": sorted(by_path.items(), key=lambda x: -x[1])[:10],
            "sources": sorted(by_source.items(), key=lambda x: -x[1])[:10]}
