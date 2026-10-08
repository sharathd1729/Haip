"""Create and authenticate API keys for the public API."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import set_tenant_context
from app.models.api_key import ApiKey

KEY_PREFIX = "haip_live_"

# scope -> what it allows (also rendered in the Settings page and the docs)
SCOPES: dict[str, str] = {
    "properties:read": "List properties",
    "bookings:read": "Read bookings, including guest contact details, add-ons and payments",
    "messages:read": "Read WhatsApp templates, conversations and message delivery status",
    "messages:send": "Send WhatsApp and Instagram messages",
}

_TOUCH_EVERY = timedelta(minutes=1)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_key(db: Session, tenant_id: str, name: str, scopes: list[str], created_by: Optional[str],
               expires_in_days: Optional[int]) -> tuple[ApiKey, str]:
    """Returns the stored row and the raw key. The raw key exists only here."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(
        tenant_id=tenant_id, name=name.strip(), prefix=raw[: len(KEY_PREFIX) + 4], key_hash=hash_key(raw),
        scopes=sorted(set(scopes)), created_by=created_by,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=expires_in_days)) if expires_in_days else None,
    )
    db.add(row)
    db.flush()
    return row, raw


def _lookup(db: Session, key_hash: str) -> Optional[tuple[str, str]]:
    """(key id, tenant id) for a key hash. On Postgres the table is under RLS and
    the caller has no tenant yet, so this goes through a SECURITY DEFINER function."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT key_id, tenant_id FROM api_key_lookup(:h)"), {"h": key_hash}).first()
        return (row[0], row[1]) if row else None
    row = db.query(ApiKey.id, ApiKey.tenant_id).filter(ApiKey.key_hash == key_hash).first()
    return (row[0], row[1]) if row else None


def authenticate(db: Session, raw: str) -> Optional[ApiKey]:
    """The live key for this raw value, with the tenant context set; or None when it
    is unknown, revoked or expired."""
    if not raw or not raw.startswith(KEY_PREFIX) or len(raw) > 120:
        return None
    found = _lookup(db, hash_key(raw))
    if not found:
        return None
    key_id, tenant_id = found
    set_tenant_context(db, tenant_id)
    key = db.query(ApiKey).filter_by(id=key_id, tenant_id=tenant_id).first()
    if not key or key.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    if key.expires_at is not None:
        exp = key.expires_at if key.expires_at.tzinfo else key.expires_at.replace(tzinfo=timezone.utc)
        if exp <= now:
            return None
    last = key.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last >= _TOUCH_EVERY:     # avoid a write on every request
        key.last_used_at = now
        db.commit()
        set_tenant_context(db, tenant_id)
    return key
