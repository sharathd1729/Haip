"""Connections for the extra publishing channels (agency M3): a Facebook Page and a Google Business Profile location.

  * Facebook Page: Facebook Login (META_APP_ID/SECRET) with pages_show_list, pages_manage_posts, pages_read_engagement.
    The long-lived user token is swapped for the Pages' own tokens (Page tokens from a long-lived user token do not
    expire); every Page's token is stored encrypted, and the Page linked to the connected Instagram account is chosen
    first. Integration kind "facebook_page".
  * Google: OAuth with the business.manage scope and offline access (GOOGLE_BUSINESS_CLIENT_ID/SECRET); the refresh
    token is stored encrypted, access tokens are refreshed when they are within 5 minutes of expiry. The location is
    chosen from the account's list. Integration kind "google_business".
OAuth state is single use (Redis, read-and-delete) and remembers who started the login.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy.orm import Session

from app.adapters import google_business as gbp
from app.adapters.facebook_page import FacebookPage
from app.adapters.instagram.publishing import PublishError
from app.core.audit import append_audit
from app.core.config import settings
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

FB_KIND, GOOGLE_KIND = "facebook_page", "google_business"
FB_DIALOG = "https://www.facebook.com/v20.0/dialog/oauth"
FB_GRAPH = "https://graph.facebook.com/v20.0/"
FB_SCOPES = "pages_show_list,pages_manage_posts,pages_read_engagement"
STATE_TTL = 600
_TAKE_ONCE = "local v = redis.call('GET', KEYS[1]); if v then redis.call('DEL', KEYS[1]) end; return v"


def _redis():
    import redis
    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=3)


def _callback(path: str) -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/marketing/studio/channels/{path}/oauth-callback"


def _state(provider: str, tenant_id: str, user_id: str) -> str:
    nonce = secrets.token_urlsafe(32)
    _redis().setex(f"oauth:{provider}:{nonce}", STATE_TTL, json.dumps({"tenant_id": tenant_id, "user_id": user_id}))
    return nonce


def _take(provider: str, state: str) -> dict:
    raw = _redis().eval(_TAKE_ONCE, 1, f"oauth:{provider}:{state}")
    if not raw:
        raise MarketingError(400, "state_expired", "This login link expired or was already used. Try again.")
    return json.loads(raw)


def connection(db: Session, tenant_id: str, kind: str, *, lock: bool = False) -> Optional[Integration]:
    q = db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind, status="active")
    return (q.with_for_update() if lock else q).first()


def status(db: Session, tenant_id: str) -> dict:
    fb, g = connection(db, tenant_id, FB_KIND), connection(db, tenant_id, GOOGLE_KIND)
    fbc, gc = (fb.config or {}) if fb else {}, (g.config or {}) if g else {}
    # A Page connected with a pasted System User token (marketing_meta_token) works without Facebook Login set up.
    return {"facebook": {"available": fb is not None or bool(settings.META_APP_ID and settings.META_APP_SECRET and settings.API_BASE_URL),
                         "connected": fb is not None, "page_name": fbc.get("page_name"),
                         "pages": [{"id": p["id"], "name": p.get("name")} for p in fbc.get("pages") or []]},
            "google": {"available": bool(settings.GOOGLE_BUSINESS_CLIENT_ID and settings.GOOGLE_BUSINESS_CLIENT_SECRET
                                         and settings.API_BASE_URL),
                       "connected": g is not None, "location_title": gc.get("title"),
                       "locations": [{"location": loc["location"], "title": loc.get("title")} for loc in gc.get("locations") or []]}}


def disconnect(db: Session, tenant_id: str, kind: str, actor_id: str) -> bool:
    integ = connection(db, tenant_id, kind)
    if integ is None:
        return False
    integ.status, integ.credentials_kms_blob = "disconnected", None
    append_audit(db, tenant_id=tenant_id, action=f"marketing.{kind}.disconnected", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id, payload={})
    return True


# ── Facebook Page ───────────────────────────────────────────────────────────────────────────────────────────────────

def facebook_start(tenant_id: str, user_id: str) -> str:
    if not (settings.META_APP_ID and settings.META_APP_SECRET and settings.API_BASE_URL):
        raise MarketingError(503, "facebook_not_configured", "Facebook posting is not set up on this HAIP server yet.")
    return FB_DIALOG + "?" + urlencode({"client_id": settings.META_APP_ID, "redirect_uri": _callback("facebook"),
                                        "state": _state("fbpage", tenant_id, user_id), "scope": FB_SCOPES,
                                        "response_type": "code"})


def _fb_get(path: str, params: dict, http: Optional[httpx.Client]) -> dict:
    c = http or httpx.Client(timeout=20, follow_redirects=False)
    try:
        r = c.get(FB_GRAPH + path, params=params)
    finally:
        if http is None:
            c.close()
    if r.status_code != 200:
        raise MarketingError(502, "facebook_login_failed", "Facebook did not accept the login.")
    return r.json()


def facebook_finish(db: Session, code: str, state: str, *, http: Optional[httpx.Client] = None,
                    instagram_id: Optional[str] = None) -> str:
    ctx = _take("fbpage", state)
    if instagram_id is None:                    # prefer the Page linked to the Instagram account HAIP already posts to
        ig = connection(db, ctx["tenant_id"], "instagram")
        instagram_id = ((ig.config or {}).get("instagram_business_account_id")) if ig else None
    short = _fb_get("oauth/access_token", {"client_id": settings.META_APP_ID, "client_secret": settings.META_APP_SECRET,
                                           "redirect_uri": _callback("facebook"), "code": code}, http)
    long_ = _fb_get("oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": settings.META_APP_ID,
                                           "client_secret": settings.META_APP_SECRET, "fb_exchange_token": short["access_token"]}, http)
    pages = _fb_get("me/accounts", {"fields": "id,name,access_token,instagram_business_account{id}",
                                    "access_token": long_["access_token"]}, http).get("data") or []
    pages = [p for p in pages if p.get("access_token")]
    if not pages:
        raise MarketingError(422, "no_pages", "No Facebook Page was shared with HAIP. Pick at least one Page when logging in.")
    linked = next((p for p in pages if (p.get("instagram_business_account") or {}).get("id") == instagram_id), None)
    chosen = linked or pages[0]
    integ = connection(db, ctx["tenant_id"], FB_KIND) or Integration(tenant_id=ctx["tenant_id"], kind=FB_KIND)
    integ.status = "active"
    integ.credentials_kms_blob = encrypt_credentials({"pages": {p["id"]: p["access_token"] for p in pages}})
    integ.config = {"page_id": chosen["id"], "page_name": chosen.get("name"),
                    "pages": [{"id": p["id"], "name": p.get("name")} for p in pages]}
    db.add(integ)
    db.flush()
    append_audit(db, tenant_id=ctx["tenant_id"], action="marketing.facebook_page.connected", actor_user_id=ctx["user_id"],
                 target_type="integration", target_id=integ.id, payload={"page": chosen.get("name"), "pages": len(pages)})
    return ctx["tenant_id"]


def choose_page(db: Session, tenant_id: str, page_id: str, actor_id: str) -> dict:
    integ = connection(db, tenant_id, FB_KIND)
    pages = {p["id"]: p for p in ((integ.config or {}).get("pages") or [])} if integ else {}
    if page_id not in pages:
        raise MarketingError(404, "not_found", "That Page is not one this workspace connected.")
    integ.config = {**integ.config, "page_id": page_id, "page_name": pages[page_id].get("name")}
    append_audit(db, tenant_id=tenant_id, action="marketing.facebook_page.chosen", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id, payload={"page": pages[page_id].get("name")})
    return integ.config


def facebook_publisher(db: Session, tenant_id: str) -> FacebookPage:
    integ = connection(db, tenant_id, FB_KIND)
    if integ is None or not integ.credentials_kms_blob:
        raise PublishError("Facebook Page is not connected for this workspace.", transient=False)
    page_id = (integ.config or {}).get("page_id")
    token = (decrypt_credentials(integ.credentials_kms_blob).get("pages") or {}).get(page_id)
    return FacebookPage(token, page_id)


# ── Google Business Profile ─────────────────────────────────────────────────────────────────────────────────────────

def google_start(tenant_id: str, user_id: str) -> str:
    if not status_available_google():
        raise MarketingError(503, "google_not_configured", "Google Business posting is not set up on this HAIP server yet.")
    return gbp.authorize_url(settings.GOOGLE_BUSINESS_CLIENT_ID, _callback("google"), _state("gbp", tenant_id, user_id))


def status_available_google() -> bool:
    return bool(settings.GOOGLE_BUSINESS_CLIENT_ID and settings.GOOGLE_BUSINESS_CLIENT_SECRET and settings.API_BASE_URL)


def _store_google(integ: Integration, tok: dict, refresh_token: Optional[str]) -> None:
    integ.credentials_kms_blob = encrypt_credentials({"access_token": tok["access_token"],
                                                      "refresh_token": tok.get("refresh_token") or refresh_token})
    integ.config = {**(integ.config or {}),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in") or 3600))).isoformat()}


def google_finish(db: Session, code: str, state: str, *, http: Optional[httpx.Client] = None) -> str:
    ctx = _take("gbp", state)
    try:
        tok = gbp.exchange_code(settings.GOOGLE_BUSINESS_CLIENT_ID, settings.GOOGLE_BUSINESS_CLIENT_SECRET, code,
                                _callback("google"), client=http)
        if not tok.get("refresh_token"):
            raise MarketingError(422, "no_refresh_token", "Google did not allow offline access. Remove HAIP from your Google "
                                 "account's connected apps and connect again.")
        locations = gbp.GoogleBusiness(tok["access_token"], client=http).locations()
    except PublishError as exc:
        log.warning("google_oauth_failed", tenant_id=ctx["tenant_id"], error=str(exc)[:200])
        raise MarketingError(502, "google_login_failed", "Google did not accept the login.")
    if not locations:
        raise MarketingError(422, "no_locations", "This Google account manages no Business Profile.")
    integ = connection(db, ctx["tenant_id"], GOOGLE_KIND) or Integration(tenant_id=ctx["tenant_id"], kind=GOOGLE_KIND)
    integ.status = "active"
    _store_google(integ, tok, None)
    first = locations[0]
    integ.config = {**integ.config, "locations": locations, "account": first["account"], "location": first["location"],
                    "title": first.get("title")}
    db.add(integ)
    db.flush()
    append_audit(db, tenant_id=ctx["tenant_id"], action="marketing.google_business.connected", actor_user_id=ctx["user_id"],
                 target_type="integration", target_id=integ.id, payload={"locations": len(locations)})
    return ctx["tenant_id"]


def choose_location(db: Session, tenant_id: str, location: str, actor_id: str) -> dict:
    integ = connection(db, tenant_id, GOOGLE_KIND)
    locs = {loc["location"]: loc for loc in ((integ.config or {}).get("locations") or [])} if integ else {}
    if location not in locs:
        raise MarketingError(404, "not_found", "That location is not one this Google account manages.")
    integ.config = {**integ.config, "account": locs[location]["account"], "location": location,
                    "title": locs[location].get("title")}
    append_audit(db, tenant_id=tenant_id, action="marketing.google_business.chosen", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id, payload={"title": locs[location].get("title")})
    return integ.config


def google_client(db: Session, tenant_id: str, *, http: Optional[httpx.Client] = None) -> tuple[gbp.GoogleBusiness, dict]:
    """(client with a fresh access token, the integration config with account + location)."""
    integ = connection(db, tenant_id, GOOGLE_KIND, lock=True)
    if integ is None or not integ.credentials_kms_blob:
        raise PublishError("Google Business Profile is not connected for this workspace.", transient=False)
    creds = decrypt_credentials(integ.credentials_kms_blob)
    expires = (integ.config or {}).get("expires_at")
    if not expires or datetime.fromisoformat(expires) < datetime.now(timezone.utc) + timedelta(minutes=5):
        tok = gbp.refresh(settings.GOOGLE_BUSINESS_CLIENT_ID, settings.GOOGLE_BUSINESS_CLIENT_SECRET, creds["refresh_token"],
                          client=http)
        _store_google(integ, tok, creds["refresh_token"])
        db.commit()
        creds = {"access_token": tok["access_token"]}
    return gbp.GoogleBusiness(creds["access_token"], client=http), dict(integ.config or {})
