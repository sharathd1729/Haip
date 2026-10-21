"""Connect Research (Business Discovery) and the Facebook Page channel with a pasted Meta System User token.

The alternative to Facebook Login when the HAIP server has no META_APP_ID or the app is not through App Review:
the owner generates a System User token in Meta Business Settings (with the Page and the Instagram account
assigned to that system user) and pastes it once. Nothing else is touched: the WhatsApp token and the Instagram
DM token (an Instagram Login token on graph.instagram.com) stay as they are.

  * Research   -> integration kind 'instagram_fb', the same shape Facebook Login writes ({access_token},
                  config ig_user_id / ig_username / page_name / token_expires_at), plus config source='system_user'.
  * Facebook   -> integration kind 'facebook_page' with the Pages' own tokens from /me/accounts, the Page linked to
                  HAIP's Instagram account first (same shape as marketing_channel_connections.facebook_finish).
Each is connected only when the token carries that part's permissions; the answer says what is missing.
"""
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.services import marketing_channel_connections as conns
from app.services import marketing_research_service as research
from app.services.marketing_content_service import MarketingError

FB_GRAPH = "https://graph.facebook.com/v20.0/"
RESEARCH_SCOPES = ("instagram_basic", "instagram_manage_insights", "pages_show_list")
PAGE_SCOPES = ("pages_show_list", "pages_manage_posts", "pages_read_engagement")


def _get(http: httpx.Client, path: str, params: dict) -> tuple[int, dict]:
    r = http.get(FB_GRAPH + path, params=params)
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body if isinstance(body, dict) else {}


def _upsert(db: Session, tenant_id: str, kind: str) -> Integration:
    integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind).first()
    if integ is None:
        integ = Integration(tenant_id=tenant_id, kind=kind)
        db.add(integ)
    return integ


def connect(db: Session, tenant_id: str, token: str, actor_id: str, *, http: Optional[httpx.Client] = None) -> dict:
    token = (token or "").strip()
    if token.startswith("IG"):
        raise MarketingError(422, "instagram_token", "That is an Instagram Login token. Paste a System User token from "
                             "Meta Business Settings (it starts with EAA).")
    if not token.startswith("EAA") or len(token) > 1024:
        raise MarketingError(422, "not_a_token", "That does not look like a Meta System User token (it starts with EAA).")
    c = http or httpx.Client(timeout=20, follow_redirects=False)
    try:
        code, dbg = _get(c, "debug_token", {"input_token": token, "access_token": token})
        info = dbg.get("data") or {}
        if code != 200 or not info.get("is_valid"):
            raise MarketingError(422, "token_rejected", "Meta did not accept this token. Generate a new one and paste it again.")
        scopes = set(info.get("scopes") or [])
        code, pages_body = _get(c, "me/accounts", {"fields": "id,name,access_token,instagram_business_account{id,username}",
                                                   "access_token": token})
    except httpx.HTTPError:
        raise MarketingError(502, "meta_unreachable", "Could not reach Meta. Try again in a minute.")
    finally:
        if http is None:
            c.close()
    pages = (pages_body.get("data") or []) if code == 200 else []
    if not pages:
        raise MarketingError(422, "no_pages", "This token sees no Facebook Page. In Business Settings, assign the Page and "
                             "the Instagram account to the system user, then generate the token again.")

    ig = conns.connection(db, tenant_id, "instagram")
    own_ig = (ig.config or {}).get("instagram_business_account_id") if ig else None
    linked = [p for p in pages if (p.get("instagram_business_account") or {}).get("id")]
    first = next((p for p in linked if p["instagram_business_account"]["id"] == own_ig), linked[0] if linked else None)
    expires = info.get("expires_at") or 0
    expires_iso = datetime.fromtimestamp(expires, timezone.utc).isoformat() if expires else None
    out = {"research": False, "facebook_page": False, "ig_username": None, "page_name": None,
           "token_expires_at": expires_iso, "missing": sorted(set(RESEARCH_SCOPES + PAGE_SCOPES) - scopes)}

    if first is not None and all(s in scopes for s in RESEARCH_SCOPES):
        account = first["instagram_business_account"]
        integ = _upsert(db, tenant_id, research.FB_KIND)
        integ.status, integ.credentials_kms_blob = "active", encrypt_credentials({"access_token": token})
        integ.config = {"ig_user_id": account["id"], "ig_username": account.get("username"), "page_name": first.get("name"),
                        "token_expires_at": expires_iso, "source": "system_user"}
        out.update(research=True, ig_username=account.get("username"))

    with_tokens = [p for p in pages if p.get("access_token")]
    if with_tokens and all(s in scopes for s in PAGE_SCOPES):
        chosen = first if first is not None and first.get("access_token") else with_tokens[0]
        integ = _upsert(db, tenant_id, conns.FB_KIND)
        integ.status = "active"
        integ.credentials_kms_blob = encrypt_credentials({"pages": {p["id"]: p["access_token"] for p in with_tokens}})
        integ.config = {"page_id": chosen["id"], "page_name": chosen.get("name"), "source": "system_user",
                        "pages": [{"id": p["id"], "name": p.get("name")} for p in with_tokens]}
        out.update(facebook_page=True, page_name=chosen.get("name"))

    if not (out["research"] or out["facebook_page"]):
        raise MarketingError(422, "missing_permissions", "This token is missing permissions: " + ", ".join(out["missing"])
                             + ". Tick them when generating the token.", problems=out["missing"])
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="marketing.meta_token.connected", actor_user_id=actor_id,
                 target_type="integration", target_id=None,
                 payload={"research": out["research"], "facebook_page": out["facebook_page"],
                          "ig_username": out["ig_username"], "page_name": out["page_name"]})
    return out
