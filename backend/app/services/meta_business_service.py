"""The workspace's Meta Business connection: one System User token, saved once, for ads, lead forms and
(next) Instagram messages. The token is stored encrypted and never returned; `config` keeps only what Meta said the
token can see, so the settings card needs no call to Meta to draw itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.marketing import meta_business
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.services import meta_token_expiry

KIND = "meta_business"


class SwitchRefused(Exception):
    """Instagram already has chats on the other connection type."""


class NotConnected(Exception):
    """No Meta Business token is saved for this workspace."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_row(db: Session, tenant_id: str) -> Integration | None:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=KIND).first()


def get_token(db: Session, tenant_id: str) -> str:
    row = get_row(db, tenant_id)
    if not row or row.status == "disconnected" or not row.credentials_kms_blob:
        return ""
    try:
        return decrypt_credentials(row.credentials_kms_blob).get("access_token", "") or ""
    except Exception:
        return ""


def _apply(row: Integration, info: dict, token: str) -> None:
    """Refresh what the token sees; keep the chosen page while the token still sees it, pick the only page by itself."""
    cfg = dict(row.config or {})
    pages = info["pages"]
    page = next((p for p in pages if p["id"] == cfg.get("page_id")), None) or (pages[0] if len(pages) == 1 else None)
    expiry = meta_token_expiry.fetch_expiry(token)
    cfg.update(
        {
            "token_name": info["name"],
            "permissions": info["permissions"],
            "ad_accounts": info["ad_accounts"],
            "pages": pages,
            "capabilities": info["capabilities"],
            "checked_at": _now_iso(),
            "page_id": page["id"] if page else None,
            "page_name": page["name"] if page else None,
            "token_expires_at": meta_token_expiry.iso(expiry["expires_at"])
            if expiry and expiry.get("expires_at")
            else None,
        }
    )
    row.config = cfg


def connect(db: Session, tenant_id: str, token: str) -> Integration:
    """Check the token with Meta (raises MetaAdsError when rejected), then save it encrypted."""
    token = token.strip()
    info = meta_business.inspect_token(token)
    row = get_row(db, tenant_id)
    if row is None:
        row = Integration(tenant_id=tenant_id, kind=KIND, config={}, installed_at=_now_iso())
        db.add(row)
    row.credentials_kms_blob = encrypt_credentials({"access_token": token})
    row.status = "active"
    _apply(row, info, token)
    db.flush()
    return row


def recheck(db: Session, tenant_id: str) -> Integration:
    token = get_token(db, tenant_id)
    if not token:
        raise NotConnected("No Meta Business token is saved for this workspace.")
    row = get_row(db, tenant_id)
    _apply(row, meta_business.inspect_token(token), token)
    db.flush()
    return row


def select_page(db: Session, tenant_id: str, page_id: str) -> Integration:
    row = get_row(db, tenant_id)
    if not row or not get_token(db, tenant_id):
        raise NotConnected("No Meta Business token is saved for this workspace.")
    page = next((p for p in (row.config or {}).get("pages", []) if p["id"] == page_id), None)
    if page is None:
        raise ValueError("This token cannot see that Facebook page.")
    row.config = {**(row.config or {}), "page_id": page["id"], "page_name": page["name"]}
    db.flush()
    return row


def disconnect(db: Session, tenant_id: str) -> bool:
    row = get_row(db, tenant_id)
    if not row:
        return False
    row.status, row.credentials_kms_blob, row.config = "disconnected", None, {}
    db.flush()
    return True


def status(db: Session, tenant_id: str) -> dict:
    """What the settings card shows. Never includes the token."""
    row = get_row(db, tenant_id)
    cfg = (row.config if row else None) or {}
    connected = bool(get_token(db, tenant_id))
    page = {"id": cfg["page_id"], "name": cfg.get("page_name")} if connected and cfg.get("page_id") else None
    from app.services import meta_lead_forms_service

    return {
        "lead_forms": meta_lead_forms_service.status_block(db, tenant_id, cfg if connected else {}),
        "instagram": instagram_block(db, tenant_id),
        "connected": connected,
        "token_name": cfg.get("token_name") if connected else None,
        "capabilities": cfg.get("capabilities") if connected else None,
        "pages": cfg.get("pages", []) if connected else [],
        "ad_accounts": cfg.get("ad_accounts", []) if connected else [],
        "page": page,
        "checked_at": cfg.get("checked_at") if connected else None,
        "token_expires_at": cfg.get("token_expires_at") if connected else None,
    }


# ── Instagram messages on this token (the other way is Instagram Login) ──────


def _instagram_row(db: Session, tenant_id: str) -> Integration | None:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram").first()


def _instagram_mode(row: Integration | None) -> str | None:
    """meta_business | instagram_login | None (nothing that can work is connected)."""
    if not row or row.status == "disconnected" or not row.credentials_kms_blob:
        return None
    if (row.config or {}).get("auth_mode") == "meta_business":
        return "meta_business"
    try:
        token = decrypt_credentials(row.credentials_kms_blob).get("access_token", "") or ""
    except Exception:
        token = ""
    return "instagram_login" if token.startswith("IG") else None


def instagram_chats_exist(db: Session, tenant_id: str) -> bool:
    from app.models.conversation import ChannelType, Conversation

    return db.query(Conversation.id).filter_by(tenant_id=tenant_id, channel=ChannelType.INSTAGRAM).first() is not None


def instagram_block(db: Session, tenant_id: str) -> dict:
    row = _instagram_row(db, tenant_id)
    mode = _instagram_mode(row)
    cfg = (row.config if row else None) or {}
    return {
        "mode": mode,
        "username": cfg.get("username") if mode else None,
        "webhook_subscribed": bool(cfg.get("webhook_subscribed")) if mode else False,
    }


def use_for_instagram(db: Session, tenant_id: str, app_secret: str) -> Integration:
    """Run the workspace's Instagram messages on this connection: the linked page's own token on graph.facebook.com,
    saved on the Instagram integration so every sender and check keeps reading one place.
    Raises NotConnected, SwitchRefused, ValueError (plain words) or MetaAdsError."""
    from app.adapters.instagram import meta_graph

    token = get_token(db, tenant_id)
    row = get_row(db, tenant_id)
    if not token or not row:
        raise NotConnected("No Meta Business token is saved for this workspace.")
    cfg = row.config or {}
    cap = (cfg.get("capabilities") or {}).get("instagram_dm") or {}
    if not cap.get("ok"):
        raise ValueError(
            "This token cannot run Instagram messages: " + "; ".join(cap.get("missing") or ["unknown reason"]) + "."
        )
    page = next((p for p in cfg.get("pages", []) if p["id"] == cfg.get("page_id")), None)
    if not page or not page.get("instagram_id"):
        raise ValueError("The chosen Facebook page has no Instagram account linked to it.")
    ig = _instagram_row(db, tenant_id)
    if _instagram_mode(ig) == "instagram_login" and instagram_chats_exist(db, tenant_id):
        raise SwitchRefused(
            "This workspace already has Instagram chats through Instagram Login. Meta's two connection types do not "
            "share ids, so switching could split each guest in two. Keep Instagram Login, or ask HAIP to migrate the chats first."
        )
    page_access = meta_business.page_token(token, page["id"])
    if not page_access:
        raise ValueError("The token can no longer see the chosen Facebook page. Use Check again.")
    subscribed, error = meta_graph.subscribe_page(page_access, page["id"])
    if ig is None:
        ig = Integration(tenant_id=tenant_id, kind="instagram", config={}, installed_at=_now_iso())
        db.add(ig)
    old: dict = {}
    if ig.credentials_kms_blob:
        try:
            old = decrypt_credentials(ig.credentials_kms_blob)
        except Exception:
            old = {}
    ig.credentials_kms_blob = encrypt_credentials(
        {
            **old,
            "access_token": page_access,
            "app_secret": app_secret.strip(),
            "instagram_business_account_id": page["instagram_id"],
        }
    )
    keep = {
        k: v for k, v in (ig.config or {}).items() if k not in ("token_expires_at", "token_refreshed_at", "permissions")
    }
    ig.config = {
        **keep,
        "auth_mode": "meta_business",
        "instagram_business_account_id": page["instagram_id"],
        "username": page.get("instagram_username") or "",
        "page_id": page["id"],
        "webhook_subscribed": subscribed,
        "webhook_subscribe_error": error or None,
        "webhook_subscribed_at": _now_iso() if subscribed else None,
    }
    ig.status = "active"
    db.flush()
    return ig
