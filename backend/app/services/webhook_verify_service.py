"""Per-workspace, per-channel webhook verify tokens for Meta (WhatsApp and Instagram).

Meta calls GET /webhooks/{whatsapp,instagram}?hub.verify_token=... once, when someone saves the
callback URL in the Meta app. That request names no workspace, so the token itself says which one:

    <workspace slug>.<random>

The handler reads the slug, loads that workspace's integration for the channel, and compares the rest
in constant time. A token for one channel never verifies the other, and one workspace's token never
verifies another's. The token is stored encrypted inside the integration's credential blob and is only
ever shown to an owner, on request.

The old single shared token (settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN) is still accepted while
settings.ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN is true, so rolling this out never breaks a working setup.
Turn that off once every channel has been re-saved in Meta with its own token.
"""
from __future__ import annotations

import secrets
from hmac import compare_digest
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import set_tenant_context
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.models.tenant import Tenant

KEY = "webhook_verify_token"

# Integration kinds that make up each channel (WhatsApp rows are "whatsapp_meta", older ones "whatsapp").
CHANNEL_KINDS: dict[str, tuple[str, ...]] = {
    "whatsapp_meta": ("whatsapp_meta", "whatsapp"),
    "instagram": ("instagram",),
}


def _blob(i: Integration) -> dict:
    if not i.credentials_kms_blob:
        return {}
    raw = bytes(i.credentials_kms_blob) if isinstance(i.credentials_kms_blob, memoryview) else i.credentials_kms_blob
    try:
        return decrypt_credentials(raw)
    except Exception:  # noqa: BLE001 -- an unreadable blob simply has no token
        return {}


def find_integration(db: Session, tenant_id: str, channel: str) -> Optional[Integration]:
    rows = db.query(Integration).filter(Integration.tenant_id == tenant_id, Integration.kind.in_(CHANNEL_KINDS[channel])).all()
    return next((r for r in rows if r.status != "disconnected"), rows[0] if rows else None)


def _new_token(slug: str) -> str:
    return f"{slug}.{secrets.token_urlsafe(24)}"


def current_token(db: Session, tenant_id: str, channel: str) -> Optional[str]:
    intg = find_integration(db, tenant_id, channel)
    return _blob(intg).get(KEY) if intg else None


def hint(token: Optional[str]) -> Optional[str]:
    return f"...{token[-4:]}" if token else None


def issue_token(db: Session, tenant: Tenant, channel: str, rotate: bool = False) -> Optional[str]:
    """The channel's token; created when missing (or replaced when rotate=True). None if the channel has no integration yet."""
    intg = find_integration(db, tenant.id, channel)
    if intg is None:
        return None
    creds = _blob(intg)
    if rotate or not creds.get(KEY):
        creds[KEY] = _new_token(tenant.slug)
        intg.credentials_kms_blob = encrypt_credentials(creds)
    return creds[KEY]


def verify(db: Session, channel: str, presented: Optional[str]) -> bool:
    """True when `presented` is a valid verify token for this channel."""
    presented = presented or ""
    if not presented:
        return False
    if "." in presented:
        slug = presented.rsplit(".", 1)[0]
        tenant = db.query(Tenant).filter_by(slug=slug, is_active=True).first()
        if tenant:
            set_tenant_context(db, tenant.id)
            stored = current_token(db, tenant.id, channel)
            if stored and compare_digest(presented, stored):
                return True
    legacy = settings.META_WHATSAPP_WEBHOOK_VERIFY_TOKEN
    return bool(settings.ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN and legacy and compare_digest(presented, legacy))
