"""Sites: create, settings, serialisation. Versions live in website_version_service, domains in website_domain_service.

A tenant has at most one site for now (the product is "your property's website"). Creating it writes:
the site row, version 1 (a complete draft from website_defaults, origin "seed") and the free subdomain.
"""
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.config import settings as app_settings
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.website import Site, SiteDomain, SiteVersion
from app.schemas.website import SiteSettings
from app.services import website_blocks as wb
from app.services import website_defaults

RESERVED_SLUGS = {"www", "app", "api", "admin", "mail", "status", "docs", "sites", "haip", "genhaip", "static", "cdn"}


class WebsiteError(Exception):
    def __init__(self, status: int, code: str, message: str, problems: Optional[list[str]] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.problems = status, code, message, problems or []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_site(db: Session, tenant_id: str) -> Optional[Site]:
    return db.query(Site).filter_by(tenant_id=tenant_id).order_by(Site.created_at).first()


def require_site(db: Session, tenant_id: str) -> Site:
    site = get_site(db, tenant_id)
    if not site:
        raise WebsiteError(404, "no_site", "This workspace has no website yet.")
    return site


def slugify(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (raw or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:40].strip("-")
    return s if len(s) >= 3 else (s + "-site").strip("-")


def _free_slug(db: Session, wanted: str) -> str:
    base = slugify(wanted)
    if base in RESERVED_SLUGS:
        base = f"{base}-stays"
    candidate, n = base, 2
    while db.query(Site.id).filter(Site.slug == candidate).first() or \
            db.query(SiteDomain.id).filter(SiteDomain.hostname == f"{candidate}.{app_settings.SITES_BASE_DOMAIN}").first():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def bookable_properties(db: Session, tenant_id: str, only_ids: Optional[list[str]] = None) -> list[Property]:
    """Active properties a guest can see. Placeholder vehicles ("Unassigned ...") are never shown or booked: the
    booking clash check deliberately ignores them, so a website booking against one could double-book."""
    q = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    props = [p for p in q.all() if not (p.name or "").strip().lower().startswith("unassigned")]
    if only_ids:
        props = [p for p in props if p.id in set(only_ids)]
    return sorted(props, key=lambda p: (p.name or "").lower())


def default_settings(db: Session, tenant: Tenant) -> SiteSettings:
    from app.services import business_data_service as bds
    from app.services.price_policy import price_mode

    deposit, balance_days = 30, 7
    try:
        rec = bds.get_effective(db, tenant.id, "payment_policy", "default")
        data = rec.data if rec else None
        if isinstance(data, dict):
            deposit = int(float(data.get("advance_percent") or deposit))
            balance_days = int(data.get("balance_due_days_before_checkin") or balance_days)
    except Exception:   # noqa: BLE001 -- a malformed policy record must not block creating a site
        pass
    return SiteSettings(
        booking_mode="request",                 # nothing is charged until an owner picks instant or deposit
        deposit_percent=max(10, min(100, deposit)),
        balance_due_days=max(0, min(60, balance_days)),
        show_prices=price_mode(tenant) == "grounded",
    )


def site_settings(site: Site) -> SiteSettings:
    try:
        return SiteSettings(**(site.settings or {}))
    except ValueError:
        return SiteSettings.model_construct(**{**SiteSettings().model_dump(), **(site.settings or {})})


def create_site(db: Session, tenant: Tenant, *, actor_id: Optional[str], name: Optional[str] = None,
                slug: Optional[str] = None) -> Site:
    if get_site(db, tenant.id):
        raise WebsiteError(409, "site_exists", "This workspace already has a website.")
    profile = (tenant.brand_config or {}).get("business_profile") or {}
    display = (name or tenant.brand_name or tenant.name or "Our stay").strip()[:160]
    cfg = default_settings(db, tenant)
    props = bookable_properties(db, tenant.id)
    city = next((p.city for p in props if p.city), None) or profile.get("city")
    contact = {"phone": profile.get("contact_phone") or "", "whatsapp": profile.get("contact_phone") or "",
               "email": profile.get("contact_email") or "", "address": next((p.address for p in props if p.address), "") or ""}
    doc = website_defaults.build(name=display, business_type=tenant.business_type, profile=profile, city=city,
                                 contact=contact, booking_mode=cfg.booking_mode)
    from app.services.website_version_service import sha_of

    site = Site(tenant_id=tenant.id, name=display, slug=_free_slug(db, slug or tenant.slug or display),
                status="draft", settings=cfg.model_dump(), created_by=actor_id)
    db.add(site)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise WebsiteError(409, "slug_taken", "That web address is taken. Try another.")
    v = SiteVersion(tenant_id=tenant.id, site_id=site.id, number=1, doc=doc, sha256=sha_of(doc), status="draft",
                    origin="seed", created_by=actor_id, note="First draft from your HAIP data")
    db.add(v)
    db.flush()
    site.draft_version_id = v.id
    db.add(SiteDomain(tenant_id=tenant.id, site_id=site.id, hostname=f"{site.slug}.{app_settings.SITES_BASE_DOMAIN}",
                      kind="subdomain", status="active", verify_token=secrets.token_hex(16), verified_at=_now()))
    append_audit(db, tenant_id=tenant.id, actor_user_id=actor_id, action="website.created", target_type="site",
                 target_id=site.id, payload={"slug": site.slug, "pack": doc["theme"]["pack"]})
    db.flush()
    return site


def update_settings(db: Session, tenant_id: str, site: Site, data: SiteSettings, *, actor_id: str) -> Site:
    before = site_settings(site).model_dump()
    after = data.model_dump()
    if data.property_ids:
        known = {p.id for p in bookable_properties(db, tenant_id)}
        unknown = [p for p in data.property_ids if p not in known]
        if unknown:
            raise WebsiteError(422, "unknown_property", "Some selected stays are not active properties.", unknown)
    if data.booking_mode in ("instant", "deposit"):
        from app.services.payment_link_service import razorpay_credentials
        if not razorpay_credentials(db, tenant_id):
            raise WebsiteError(422, "razorpay_missing",
                               "Connect Razorpay in Settings › Payments before guests can pay on the website.")
    site.settings = after
    site.updated_at = _now()
    changed = {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="website.settings_changed",
                 target_type="site", target_id=site.id, payload={"changed": changed})
    db.flush()
    return site


def domains(db: Session, site: Site) -> list[SiteDomain]:
    return db.query(SiteDomain).filter_by(tenant_id=site.tenant_id, site_id=site.id).filter(
        SiteDomain.status != "removed").order_by(SiteDomain.kind.desc(), SiteDomain.created_at).all()


def primary_host(db: Session, site: Site) -> str:
    ds = domains(db, site)
    custom = next((d for d in ds if d.kind == "custom" and d.status == "active"), None)
    sub = next((d for d in ds if d.kind == "subdomain"), None)
    return (custom or sub).hostname if (custom or sub) else f"{site.slug}.{app_settings.SITES_BASE_DOMAIN}"


def site_out(db: Session, site: Site) -> dict:
    draft = db.get(SiteVersion, site.draft_version_id) if site.draft_version_id else None
    live = db.get(SiteVersion, site.live_version_id) if site.live_version_id else None
    return {
        "id": site.id, "name": site.name, "slug": site.slug, "status": site.status,
        "settings": site_settings(site).model_dump(),
        "url": f"https://{primary_host(db, site)}",
        "draft": {"id": draft.id, "number": draft.number, "status": draft.status, "sha256": draft.sha256,
                  "updated_at": draft.updated_at.isoformat() if draft.updated_at else None} if draft else None,
        "live": {"id": live.id, "number": live.number, "published_at": live.published_at.isoformat() if live.published_at else None} if live else None,
        "domains": [{"id": d.id, "hostname": d.hostname, "kind": d.kind, "status": d.status, "error": d.error,
                     "verify_token": d.verify_token if d.kind == "custom" else None,
                     "cname_target": app_settings.SITES_CNAME_TARGET or f"sites.{app_settings.SITES_BASE_DOMAIN}"}
                    for d in domains(db, site)],
        "spec_version": wb.spec()["version"],
    }
