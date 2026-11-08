"""Google Search Console connection for the workspace's website (Integration kind "search_console").

* OAuth with the SAME Google Cloud OAuth client as the Business Profile (GOOGLE_BUSINESS_CLIENT_ID/SECRET), scope
  https://www.googleapis.com/auth/webmasters, offline access. The refresh token is stored encrypted
  (core.encryption), access tokens refreshed 5 minutes before expiry; no token is ever logged or returned.
  Single-use OAuth state = marketing_channel_connections (Redis, read-and-delete).
* Property: the site's hosts (website_service.domains + primary_host) are matched against the properties the Google
  account can see. A URL-prefix property ("https://www.example.com/") must name a site host exactly; a domain property
  ("sc-domain:example.com") covers the domain and every subdomain. Exact URL-prefix on the primary host wins, then a
  domain property, then any other site host. Unverified properties never count. No match = connected, owner picks.
* Sitemap: https://<primary host>/sitemap.xml is submitted when a property is chosen and whenever that URL changes
  (daily pull checks), only when the property covers the primary host and the owner has full access.
* Disconnect deletes every Search Console row (gsc_daily_totals, gsc_search_rows), like the Instagram Business
  Discovery connection deletes what came through it.
"""

from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy.orm import Session

from app.adapters import google_business as gbp
from app.adapters import google_search as gs
from app.adapters.instagram.publishing import PublishError
from app.core.audit import append_audit
from app.core.config import settings
from app.core.encryption import decrypt_credentials
from app.models.google_surfaces import GscDailyTotal, GscSearchRow
from app.models.integration import Integration
from app.services import marketing_channel_connections as conns
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

KIND = "search_console"
OWNER_LEVELS = ("siteOwner", "siteFullUser")  # may submit a sitemap
MAX_MONEY_QUERIES = 10


def available() -> bool:
    return conns.status_available_google()


def callback_url() -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/websites/google/search-console/oauth-callback"


def start(tenant_id: str, user_id: str) -> str:
    if not available():
        raise MarketingError(503, "google_not_configured", "Google sign-in is not set up on this HAIP server yet.")
    return gbp.authorize_url(
        settings.GOOGLE_BUSINESS_CLIENT_ID, callback_url(), conns._state("gsc", tenant_id, user_id), scope=gs.SCOPE
    )


def _site_hosts(db: Session, tenant_id: str) -> tuple[str | None, list[str]]:
    """(primary host, every host of the workspace's website) or (None, []) without a website."""
    from app.models.website import Site
    from app.services import website_service as wsvc

    site = db.query(Site).filter_by(tenant_id=tenant_id).order_by(Site.created_at).first()
    if site is None:
        return None, []
    primary = wsvc.primary_host(db, site)
    return primary, [primary, *[d.hostname for d in wsvc.domains(db, site) if d.hostname != primary]]


def _host_of_prefix(site_url: str) -> str | None:
    try:
        return httpx.URL(site_url).host.lower() or None
    except Exception:  # noqa: BLE001 -- not a URL
        return None


def covers(site_url: str, host: str) -> bool:
    host = host.lower()
    if site_url.startswith("sc-domain:"):
        dom = site_url[len("sc-domain:") :].lower().strip(".")
        return host == dom or host.endswith("." + dom)
    return _host_of_prefix(site_url) == host


def match_property(properties: list[dict], primary: str | None, hosts: list[str]) -> str | None:
    usable = [p for p in properties if p.get("permission") != "siteUnverifiedUser"]
    for h in ([primary] if primary else []) + [h for h in hosts if h != primary]:
        for want_domain in (False, True):  # an exact URL-prefix property beats a domain property
            hit = next(
                (
                    p
                    for p in usable
                    if p["site_url"].startswith("sc-domain:") == want_domain and covers(p["site_url"], h)
                ),
                None,
            )
            if hit:
                return hit["site_url"]
    return None


def connection(db: Session, tenant_id: str, *, lock: bool = False) -> Integration | None:
    return conns.connection(db, tenant_id, KIND, lock=lock)


def finish(db: Session, code: str, state: str, *, http: httpx.Client | None = None) -> str:
    ctx = conns._take("gsc", state)
    try:
        tok = gbp.exchange_code(
            settings.GOOGLE_BUSINESS_CLIENT_ID,
            settings.GOOGLE_BUSINESS_CLIENT_SECRET,
            code,
            callback_url(),
            client=http,
        )
        if not tok.get("refresh_token"):
            raise MarketingError(
                422,
                "no_refresh_token",
                "Google did not allow offline access. Remove HAIP from your Google "
                "account's connected apps and connect again.",
            )
        properties = gs.SearchConsole(tok["access_token"], client=http).sites()
    except PublishError as exc:
        log.warning("search_console_oauth_failed", tenant_id=ctx["tenant_id"], status=exc.status)
        raise MarketingError(502, "google_login_failed", "Google did not accept the login.") from exc
    if not properties:
        raise MarketingError(
            422,
            "no_properties",
            "This Google account has no Search Console property. Add your website "
            "in Search Console first, then connect again.",
        )
    primary, hosts = _site_hosts(db, ctx["tenant_id"])
    integ = connection(db, ctx["tenant_id"]) or Integration(tenant_id=ctx["tenant_id"], kind=KIND)
    integ.status = "active"
    conns._store_google(integ, tok, None)
    chosen = match_property(properties, primary, hosts)
    integ.config = {**integ.config, "properties": properties, "property": chosen}
    db.add(integ)
    db.flush()
    append_audit(
        db,
        tenant_id=ctx["tenant_id"],
        action="website.search_console.connected",
        actor_user_id=ctx["user_id"],
        target_type="integration",
        target_id=integ.id,
        payload={"properties": len(properties), "matched": bool(chosen)},
    )
    if chosen:
        submit_sitemap_if_changed(db, ctx["tenant_id"], http=http)
    return ctx["tenant_id"]


def client(db: Session, tenant_id: str, *, http: httpx.Client | None = None) -> tuple[gs.SearchConsole, Integration]:
    """(client with a fresh access token, the locked integration row)."""
    integ = connection(db, tenant_id, lock=True)
    if integ is None or not integ.credentials_kms_blob:
        raise PublishError("Search Console is not connected for this workspace.", transient=False)
    creds = decrypt_credentials(integ.credentials_kms_blob)
    expires = (integ.config or {}).get("expires_at")
    if not expires or datetime.fromisoformat(expires) < datetime.now(UTC) + timedelta(minutes=5):
        tok = gbp.refresh(
            settings.GOOGLE_BUSINESS_CLIENT_ID,
            settings.GOOGLE_BUSINESS_CLIENT_SECRET,
            creds["refresh_token"],
            client=http,
        )
        conns._store_google(integ, tok, creds["refresh_token"])
        db.flush()
        creds = {"access_token": tok["access_token"]}
    return gs.SearchConsole(creds["access_token"], client=http), integ


def choose_property(db: Session, tenant_id: str, site_url: str, actor_id: str) -> dict:
    integ = connection(db, tenant_id)
    known = {p["site_url"] for p in ((integ.config or {}).get("properties") or [])} if integ else set()
    if site_url not in known:
        raise MarketingError(404, "not_found", "That property is not one this Google account can see.")
    integ.config = {**integ.config, "property": site_url}
    append_audit(
        db,
        tenant_id=tenant_id,
        action="website.search_console.property_chosen",
        actor_user_id=actor_id,
        target_type="integration",
        target_id=integ.id,
        payload={"property": site_url},
    )
    return integ.config


def set_money_queries(db: Session, tenant_id: str, queries: list[str], actor_id: str) -> list[str]:
    integ = connection(db, tenant_id)
    if integ is None:
        raise MarketingError(409, "not_connected", "Connect Search Console first.")
    clean: list[str] = []
    for q in queries:
        q = " ".join((q or "").lower().split())[:200]
        if q and q not in clean:
            clean.append(q)
    if len(clean) > MAX_MONEY_QUERIES:
        raise MarketingError(422, "too_many", f"Pick at most {MAX_MONEY_QUERIES} searches.")
    integ.config = {**integ.config, "money_queries": clean}
    append_audit(
        db,
        tenant_id=tenant_id,
        action="website.search_console.money_queries",
        actor_user_id=actor_id,
        target_type="integration",
        target_id=integ.id,
        payload={"count": len(clean)},
    )
    return clean


def money_queries(db: Session, tenant_id: str) -> list[str]:
    integ = connection(db, tenant_id)
    return list((integ.config or {}).get("money_queries") or []) if integ else []


def submit_sitemap_if_changed(db: Session, tenant_id: str, *, http: httpx.Client | None = None) -> str | None:
    """Submit https://<primary host>/sitemap.xml when it differs from the one last submitted. Returns what happened."""
    integ = connection(db, tenant_id)
    cfg = (integ.config or {}) if integ else {}
    prop = cfg.get("property")
    primary, _ = _site_hosts(db, tenant_id)
    if not prop or not primary:
        return None
    sitemap = f"https://{primary}/sitemap.xml"
    if cfg.get("sitemap_submitted") == sitemap:
        return "unchanged"
    level = next((p.get("permission") for p in cfg.get("properties") or [] if p["site_url"] == prop), None)
    if not covers(prop, primary) or level not in OWNER_LEVELS:
        integ.config = {
            **cfg,
            "sitemap_problem": "This Google account cannot submit a sitemap for your website's address.",
        }
        return "not_allowed"
    sc, integ = client(db, tenant_id, http=http)
    try:
        sc.submit_sitemap(prop, sitemap)
    except PublishError as exc:
        integ.config = {**integ.config, "sitemap_problem": f"Google refused the sitemap ({exc.status or 'no answer'})."}
        log.warning("search_console_sitemap_failed", tenant_id=tenant_id, status=exc.status)
        return "failed"
    integ.config = {
        **{k: v for k, v in integ.config.items() if k != "sitemap_problem"},
        "sitemap_submitted": sitemap,
        "sitemap_submitted_at": datetime.now(UTC).isoformat(),
    }
    return "submitted"


def disconnect(db: Session, tenant_id: str, actor_id: str) -> dict:
    integ = connection(db, tenant_id)
    totals = db.query(GscDailyTotal).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    rows = db.query(GscSearchRow).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    if integ is not None:
        integ.status, integ.credentials_kms_blob = "disconnected", None
    append_audit(
        db,
        tenant_id=tenant_id,
        action="website.search_console.disconnected",
        actor_user_id=actor_id,
        target_type="integration",
        target_id=integ.id if integ else None,
        payload={"deleted_totals": totals, "deleted_rows": rows},
    )
    return {"deleted_totals": totals, "deleted_rows": rows}


def status(db: Session, tenant_id: str) -> dict:
    integ = connection(db, tenant_id)
    cfg = (integ.config or {}) if integ else {}
    return {
        "available": available(),
        "connected": integ is not None,
        "property": cfg.get("property"),
        "properties": [
            {"site_url": p["site_url"], "permission": p.get("permission")} for p in cfg.get("properties") or []
        ],
        "sitemap_submitted": cfg.get("sitemap_submitted"),
        "sitemap_problem": cfg.get("sitemap_problem"),
        "money_queries": list(cfg.get("money_queries") or []),
        "pull": cfg.get("metrics_pull") or {},
    }
