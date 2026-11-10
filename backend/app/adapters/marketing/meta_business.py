"""A Meta Business (System User) token: who it belongs to, what it may do, and which assets it sees.

One token can serve ads, lead forms and Instagram messages, so the workspace saves it once. Every call goes through
`meta_ads._get`, which pins the host to graph.facebook.com (also for `paging.next`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from app.adapters.marketing import meta_ads
from app.adapters.marketing.meta_ads import GRAPH, MetaAdsError

# capability -> permissions the token must hold
NEEDS = {
    "ads": ("ads_read",),
    "lead_forms": ("leads_retrieval", "pages_manage_ads", "pages_read_engagement", "pages_show_list"),
    "instagram_dm": ("instagram_manage_messages", "pages_messaging", "pages_show_list"),
}
LEAD_FIELDS = "id,created_time,field_data,ad_id,adset_id,campaign_id,form_id,platform"


def _soft(call, default):
    """An asset list the token may not read counts as empty; a throttle or a dead token still raises."""
    try:
        return call()
    except MetaAdsError as exc:
        if exc.rate_limited or exc.code == 190:
            raise
        return default


def list_pages(token: str) -> list[dict]:
    """Facebook pages the token manages: [{id, name, instagram_id, instagram_username}]."""
    params = {"access_token": token, "limit": 100}
    try:
        body = meta_ads._get(
            f"{GRAPH}/me/accounts", {**params, "fields": "id,name,instagram_business_account{id,username}"}
        )
    except MetaAdsError as exc:
        if exc.rate_limited or exc.code == 190:
            raise
        body = meta_ads._get(f"{GRAPH}/me/accounts", {**params, "fields": "id,name"})
    out = []
    for p in body.get("data", []):
        ig = p.get("instagram_business_account") or {}
        out.append(
            {
                "id": str(p.get("id")),
                "name": p.get("name") or "",
                "instagram_id": ig.get("id"),
                "instagram_username": ig.get("username"),
            }
        )
    return out


def capabilities(permissions: list[str], ad_accounts: list[dict], pages: list[dict]) -> dict:
    """{capability: {ok, missing: [plain words]}}: what this token can be used for, and what is in the way."""
    have = set(permissions)
    out = {}
    for name, needed in NEEDS.items():
        missing = [f"permission {p}" for p in needed if p not in have]
        if name == "ads" and not ad_accounts:
            missing.append("no ad account is assigned to this system user")
        if name == "lead_forms" and not pages:
            missing.append("no Facebook page is assigned to this system user")
        if name == "instagram_dm" and not any(p.get("instagram_id") for p in pages):
            missing.append("no Instagram account is linked to a page this token can see")
        out[name] = {"ok": not missing, "missing": missing}
    return out


def inspect_token(token: str) -> dict:
    """Raises MetaAdsError when Meta rejects the token."""
    me = meta_ads._get(f"{GRAPH}/me", {"access_token": token, "fields": "id,name"})
    granted = meta_ads._get(f"{GRAPH}/me/permissions", {"access_token": token, "limit": 200}).get("data", [])
    permissions = sorted(p.get("permission") for p in granted if p.get("status") == "granted" and p.get("permission"))
    ad_accounts = _soft(lambda: meta_ads.list_ad_accounts(token), [])
    pages = _soft(lambda: list_pages(token), [])
    return {
        "name": me.get("name") or "",
        "permissions": permissions,
        "ad_accounts": ad_accounts,
        "pages": pages,
        "capabilities": capabilities(permissions, ad_accounts, pages),
    }


# ── lead forms (read with the page's own token) ───────────────────────────────


def page_token(token: str, page_id: str) -> str | None:
    body = meta_ads._get(f"{GRAPH}/me/accounts", {"access_token": token, "fields": "id,access_token", "limit": 100})
    for p in body.get("data", []):
        if str(p.get("id")) == str(page_id):
            return p.get("access_token")
    return None


def _paged(url: str, params: dict, max_pages: int) -> Iterator[dict]:
    body = meta_ads._get(url, params)
    pages = 0
    while True:
        yield from body.get("data", [])
        nxt = (body.get("paging") or {}).get("next")
        pages += 1
        if not nxt or pages >= max_pages:
            break
        body = meta_ads._get(nxt)


def list_lead_forms(page_access_token: str, page_id: str) -> list[dict]:
    rows = _paged(
        f"{GRAPH}/{page_id}/leadgen_forms",
        {"access_token": page_access_token, "fields": "id,name,status,leads_count", "limit": 100},
        5,
    )
    return [
        {
            "id": str(f.get("id")),
            "name": f.get("name") or "",
            "status": f.get("status") or "",
            "leads_count": f.get("leads_count"),
        }
        for f in rows
    ]


def fetch_leads(page_access_token: str, form_id: str, since_unix: int, *, max_pages: int = 20) -> Iterator[dict]:
    """Leads of one form created after `since_unix` (raw Graph objects)."""
    flt = json.dumps([{"field": "time_created", "operator": "GREATER_THAN", "value": int(since_unix)}])
    yield from _paged(
        f"{GRAPH}/{form_id}/leads",
        {"access_token": page_access_token, "fields": LEAD_FIELDS, "filtering": flt, "limit": 100},
        max_pages,
    )
