"""Research analyst API (agency phase B). Module `marketing_studio`.

GET    /marketing/studio/research                         competitors, latest brief, Facebook connection state
POST   /marketing/studio/research/competitors             add a competitor handle (marketing.edit)
DELETE /marketing/studio/research/competitors/{id}
POST   /marketing/studio/research/competitors/{id}/posts  paste a competitor post (stored as text, never fetched)
POST   /marketing/studio/research/refresh                 snapshot competitors + new brief (async)
GET    /marketing/studio/research/facebook/oauth-start    Facebook Login for Business Discovery (owner/manager)
GET    /marketing/studio/research/facebook/oauth-callback Meta redirects here; single-use state from Redis
POST   /marketing/studio/research/facebook/token          owner: paste a System User token instead (Research + Facebook Page)
DELETE /marketing/studio/research/facebook                disconnect + delete all API-sourced competitor data (owner)
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.config import settings
from app.core.database import get_db
from app.core.encryption import encrypt_credentials
from app.core.security import decode_token
from app.models.integration import Integration
from app.models.marketing import MarketingCompetitorSnapshot, MarketingResearchBrief
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.marketing_research import CompetitorIn, CompetitorPostIn
from app.services import marketing_content_service as svc
from app.services import marketing_meta_token as meta_token
from app.services import marketing_research_service as research
from app.services.authz_service import require_capability

log = structlog.get_logger()
router = APIRouter(prefix="/marketing/studio/research", tags=["marketing-research"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_owner = Depends(require_capability("settings.manage"))

FB_GRAPH = "https://graph.facebook.com/v20.0/"
FB_DIALOG = "https://www.facebook.com/v20.0/dialog/oauth"
FB_SCOPES = "instagram_basic,instagram_manage_insights,pages_show_list,pages_read_engagement,business_management"
STATE_TTL = 600
_TAKE_ONCE = "local v = redis.call('GET', KEYS[1]); if v then redis.call('DEL', KEYS[1]) end; return v"


def _err(exc: svc.MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _redis():
    import redis
    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=3)


@router.get("")
def get_research(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    comps = research.list_competitors(db, user.tenant_id)
    out = []
    for c in comps:
        snap = (db.query(MarketingCompetitorSnapshot).filter_by(tenant_id=user.tenant_id, competitor_id=c.id)
                .order_by(MarketingCompetitorSnapshot.created_at.desc()).first())
        out.append({"id": c.id, "handle": c.handle, "display_name": c.display_name, "notes": c.notes,
                    "followers": snap.followers_count if snap else None, "last_snapshot_at": snap.created_at if snap else None,
                    "last_error": snap.error if snap else None})
    brief = (db.query(MarketingResearchBrief).filter_by(tenant_id=user.tenant_id)
             .order_by(MarketingResearchBrief.created_at.desc()).first())
    integ = research.fb_connection(db, user.tenant_id)
    return {"competitors": out, "max_competitors": research.MAX_COMPETITORS,
            "facebook": {"status": integ.status if integ else "not_connected",
                         "username": (integ.config or {}).get("ig_username") if integ else None,
                         "error": (integ.config or {}).get("last_error") if integ else None,
                         "source": (integ.config or {}).get("source", "facebook_login") if integ else None,
                         "login_available": bool(settings.META_APP_ID and settings.API_BASE_URL)},
            "brief": brief and {"id": brief.id, "status": brief.status, "error": brief.error, "measured": brief.measured,
                                "assessment": brief.assessment, "created_at": brief.created_at, "model": brief.model}}


@router.post("/competitors", status_code=201)
def add_competitor(body: CompetitorIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   _m=_module, _c=_edit):
    try:
        comp = research.add_competitor(db, user.tenant_id, body, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"id": comp.id, "handle": comp.handle}


@router.delete("/competitors/{competitor_id}")
def remove_competitor(competitor_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                      _m=_module, _c=_edit):
    try:
        research.remove_competitor(db, user.tenant_id, competitor_id, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"ok": True}


@router.post("/competitors/{competitor_id}/posts", status_code=201)
def add_post(competitor_id: str, body: CompetitorPostIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db), _m=_module, _c=_edit):
    try:
        post = research.add_manual_post(db, user.tenant_id, competitor_id, body, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"id": post.id, "source": post.source}


@router.post("/refresh", status_code=202)
def refresh(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import research_refresh
    try:
        research_refresh.delay(user.tenant_id, user.id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                     "problems": []})
    return {"status": "queued"}


# ── Facebook Login (Business Discovery) ─────────────────────────────────────────────────────────────────────────────

def _callback_url() -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/marketing/studio/research/facebook/oauth-callback"


def _back(status: str, reason: str = "") -> RedirectResponse:
    q = urlencode({"tab": "research", "fb": status, **({"reason": reason[:120]} if reason else {})})
    return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/marketing/studio?{q}", status_code=302)


@router.get("/facebook/oauth-start")
def fb_oauth_start(token: str = Query(...), db: Session = Depends(get_db)):
    """Opened in the browser (a redirect), so the HAIP access token comes as ?token= like the Instagram flow."""
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.query(User).filter_by(id=decoded.get("sub"), is_active=True).first()
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    if user is None or role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only an owner or manager can connect Facebook")
    if not settings.META_APP_ID or not settings.API_BASE_URL:
        raise HTTPException(status_code=503, detail="Facebook Login is not configured (META_APP_ID / API_BASE_URL)")
    nonce = secrets.token_urlsafe(32)
    try:
        _redis().setex(f"oauth:fb:{nonce}", STATE_TTL, json.dumps({"tenant_id": user.tenant_id, "user_id": user.id}))
    except Exception:  # noqa: BLE001 -- no single-use state, no login
        raise HTTPException(status_code=503, detail="Login is unavailable right now (state store down)")
    params = {"client_id": settings.META_APP_ID, "redirect_uri": _callback_url(), "state": nonce, "scope": FB_SCOPES,
              "response_type": "code"}
    return RedirectResponse(f"{FB_DIALOG}?{urlencode(params)}", status_code=302)


def _fb_get(path: str, params: dict) -> dict:
    r = httpx.get(FB_GRAPH + path, params=params, timeout=20, follow_redirects=False)
    if r.status_code != 200:
        raise ValueError(f"Facebook {r.status_code}: {r.text[:200]}")
    return r.json()


@router.get("/facebook/oauth-callback")
def fb_oauth_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None),
                      db: Session = Depends(get_db)):
    if error or not code or not state:
        return _back("error", error or "Login was cancelled.")
    try:
        # Single use: atomic read-and-delete (Lua, so it also works on Redis older than 6.2's GETDEL).
        raw = _redis().eval(_TAKE_ONCE, 1, f"oauth:fb:{state}")
    except Exception:  # noqa: BLE001
        raw = None
    if not raw:
        return _back("error", "This login link expired or was already used. Try again.")
    ctx = json.loads(raw)
    try:
        short = _fb_get("oauth/access_token", {"client_id": settings.META_APP_ID, "client_secret": settings.META_APP_SECRET,
                                               "redirect_uri": _callback_url(), "code": code})
        long_ = _fb_get("oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": settings.META_APP_ID,
                                               "client_secret": settings.META_APP_SECRET, "fb_exchange_token": short["access_token"]})
        token = long_["access_token"]
        pages = _fb_get("me/accounts", {"fields": "name,instagram_business_account{id,username}", "access_token": token})
    except (ValueError, KeyError, httpx.HTTPError) as exc:
        log.warning("fb_oauth_exchange_failed", tenant_id=ctx["tenant_id"], error=str(exc)[:200])
        return _back("error", "Facebook did not accept the login.")
    linked = next((p for p in pages.get("data", []) if p.get("instagram_business_account")), None)
    if linked is None:
        return _back("error", "No Facebook Page with a linked Instagram professional account was found.")
    ig = linked["instagram_business_account"]
    integ = research.fb_connection(db, ctx["tenant_id"]) or Integration(tenant_id=ctx["tenant_id"], kind=research.FB_KIND)
    integ.status = "active"
    integ.credentials_kms_blob = encrypt_credentials({"access_token": token})
    expires = long_.get("expires_in")
    integ.config = {"ig_user_id": ig.get("id"), "ig_username": ig.get("username"), "page_name": linked.get("name"),
                    "token_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(expires))).isoformat() if expires else None}
    db.add(integ)
    from app.core.audit import append_audit
    db.flush()
    append_audit(db, tenant_id=ctx["tenant_id"], action="marketing.instagram_fb.connected", actor_user_id=ctx["user_id"],
                 target_type="integration", target_id=integ.id, payload={"ig_username": ig.get("username")})
    db.commit()
    return _back("connected")


@router.delete("/facebook")
def fb_disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    out = research.disconnect_fb(db, user.tenant_id, user.id)
    db.commit()
    return out


class SystemTokenIn(BaseModel):
    access_token: str = Field(min_length=20, max_length=1024)


@router.post("/facebook/token")
def fb_system_token(body: SystemTokenIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    _m=_module, _c=_owner):
    """Connect Research (and the Facebook Page, when the token allows) with a System User token. WhatsApp and the
    Instagram DM connection are not touched."""
    try:
        out = meta_token.connect(db, user.tenant_id, body.access_token, user.id)
    except svc.MarketingError as exc:          # raised before anything is written
        raise _err(exc)
    db.commit()
    return out
