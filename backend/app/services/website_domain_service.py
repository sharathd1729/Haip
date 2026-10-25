"""Custom domains for a site.

Owner adds "www.myvilla.in" -> HAIP shows two DNS records to create:
  TXT   _haip-verify.www.myvilla.in   = <verify_token>     (proves they control the domain)
  CNAME www.myvilla.in                -> SITES_CNAME_TARGET (sends visitors to HAIP)
verify() reads DNS over HTTPS from a fixed resolver (cloudflare-dns.com, host-pinned, no user-supplied URL is ever
fetched). With CLOUDFLARE_API_TOKEN + CLOUDFLARE_ZONE_ID set, a verified domain is also registered as a Cloudflare for
SaaS custom hostname so TLS is issued automatically; without them the proxy operator issues the certificate.
"""
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.config import settings as app_settings
from app.models.website import Site, SiteDomain
from app.services.website_service import WebsiteError

log = structlog.get_logger()
DOH_URL = "https://cloudflare-dns.com/dns-query"
CF_API = "https://api.cloudflare.com/client/v4"
HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_CUSTOM = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cname_target() -> str:
    return app_settings.SITES_CNAME_TARGET or app_settings.SITES_BASE_DOMAIN


def add(db: Session, site: Site, hostname: str, *, actor_id: str) -> SiteDomain:
    h = hostname.strip().lower().rstrip(".")
    if h.startswith("http"):
        h = re.sub(r"^https?://", "", h).split("/")[0]
    if not HOST_RE.match(h):
        raise WebsiteError(422, "bad_hostname", "Enter a domain like www.yourvilla.in (no https:// or paths).")
    base = app_settings.SITES_BASE_DOMAIN.lower()
    if h == base or h.endswith("." + base) or h.endswith("genhaip.com"):
        raise WebsiteError(422, "reserved_hostname", "That domain belongs to HAIP. Use your own domain.")
    existing = db.query(SiteDomain).filter(SiteDomain.hostname == h).first()
    if existing and existing.status != "removed":
        raise WebsiteError(409, "hostname_taken", "That domain is already connected to a website.")
    count = db.query(SiteDomain).filter(SiteDomain.site_id == site.id, SiteDomain.kind == "custom",
                                        SiteDomain.status != "removed").count()
    if count >= MAX_CUSTOM:
        raise WebsiteError(422, "too_many_domains", f"A site can have up to {MAX_CUSTOM} custom domains.")
    if existing:   # a removed row for the same host: reuse it
        existing.site_id, existing.tenant_id, existing.status = site.id, site.tenant_id, "pending"
        existing.verify_token, existing.error, existing.verified_at = secrets.token_hex(16), None, None
        d = existing
        db.flush()
    else:
        d = SiteDomain(tenant_id=site.tenant_id, site_id=site.id, hostname=h, kind="custom", status="pending",
                       verify_token=secrets.token_hex(16))
        try:
            with db.begin_nested():      # another workspace's row (invisible under RLS) still holds the unique name
                db.add(d)
                db.flush()
        except IntegrityError:
            raise WebsiteError(409, "hostname_taken", "That domain is already connected to a website.")
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor_id, action="website.domain_added",
                 target_type="site_domain", target_id=d.id, payload={"hostname": h})
    return d


def _doh(name: str, rtype: str) -> list[str]:
    r = httpx.get(DOH_URL, params={"name": name, "type": rtype}, headers={"accept": "application/dns-json"},
                  timeout=8.0, follow_redirects=False)
    r.raise_for_status()
    return [str(a.get("data", "")).strip('"').rstrip(".").lower() for a in (r.json().get("Answer") or [])]


def _cloudflare_register(hostname: str) -> Optional[str]:
    if not (app_settings.CLOUDFLARE_API_TOKEN and app_settings.CLOUDFLARE_ZONE_ID):
        return None
    r = httpx.post(f"{CF_API}/zones/{app_settings.CLOUDFLARE_ZONE_ID}/custom_hostnames",
                   headers={"Authorization": f"Bearer {app_settings.CLOUDFLARE_API_TOKEN}"},
                   json={"hostname": hostname, "ssl": {"method": "http", "type": "dv"}}, timeout=15.0, follow_redirects=False)
    if r.status_code >= 400:
        raise RuntimeError(f"cloudflare {r.status_code}")
    return str((r.json().get("result") or {}).get("id") or "") or None


def verify(db: Session, d: SiteDomain, *, actor_id: Optional[str] = None) -> SiteDomain:
    if d.kind != "custom" or d.status in ("active", "removed"):
        return d
    d.last_checked_at = _now()
    try:
        txt = _doh(f"_haip-verify.{d.hostname}", "TXT")
        cname = _doh(d.hostname, "CNAME")
    except Exception as exc:  # noqa: BLE001 -- DNS lookups fail transiently; keep pending and try again later
        d.error = "We couldn't check DNS just now. We'll try again."
        log.warning("website_domain_dns_failed", domain_id=d.id, error=type(exc).__name__)
        return d
    if d.verify_token not in txt:
        d.status, d.error = "pending", "The TXT record isn't visible yet. DNS changes can take up to a few hours."
        return d
    target = cname_target().lower()
    if target not in cname:
        d.status, d.error = "verified", f"Ownership confirmed. Now point {d.hostname} (CNAME) to {target}."
        d.verified_at = d.verified_at or _now()
        return d
    try:
        ref = _cloudflare_register(d.hostname)
        if ref:
            d.provider_ref = ref
    except Exception as exc:  # noqa: BLE001
        d.status, d.error = "verified", "DNS is right; the certificate request failed. We'll retry."
        log.error("website_domain_tls_failed", domain_id=d.id, error=str(exc)[:200])
        return d
    d.status, d.error = "active", None
    d.verified_at = d.verified_at or _now()
    append_audit(db, tenant_id=d.tenant_id, actor_user_id=actor_id, action="website.domain_active",
                 target_type="site_domain", target_id=d.id, payload={"hostname": d.hostname})
    return d


def remove(db: Session, site: Site, domain_id: str, *, actor_id: str) -> None:
    d = db.query(SiteDomain).filter_by(id=domain_id, site_id=site.id, tenant_id=site.tenant_id).first()
    if not d or d.status == "removed":
        raise WebsiteError(404, "domain_not_found", "That domain isn't connected.")
    if d.kind == "subdomain":
        raise WebsiteError(422, "subdomain_fixed", "The free HAIP address can't be removed.")
    d.status, d.error = "removed", None
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor_id, action="website.domain_removed",
                 target_type="site_domain", target_id=d.id, payload={"hostname": d.hostname})


def pending(db: Session, tenant_id: str) -> list[SiteDomain]:
    return db.query(SiteDomain).filter(SiteDomain.tenant_id == tenant_id, SiteDomain.kind == "custom",
                                       SiteDomain.status.in_(("pending", "verified"))).all()
