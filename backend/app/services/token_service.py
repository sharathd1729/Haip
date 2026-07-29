"""Personal access tokens for HAIP's MCP server (external AI-assistant
access, e.g. Perisclaw). Modeled on RefreshToken's hash-only storage --
see auth.py's token_hash usage for the same hashing convention."""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.mcp_token import PersonalAccessToken

_TOKEN_PREFIX = "haip_pat_"


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_token(
    db: Session,
    tenant_id: str,
    user_id: str,
    name: str,
    scopes: Optional[list[str]] = None,
) -> tuple[str, PersonalAccessToken]:
    """Creates a new PAT. Returns (raw_token, record) -- raw_token is never
    persisted and must be shown to the caller exactly once."""
    raw_token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    record = PersonalAccessToken(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        token_hash=_hash(raw_token),
        scopes=scopes or ["read", "write"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_token, record


def verify_token(db: Session, raw_token: str) -> Optional[PersonalAccessToken]:
    """Looks up a PAT by hash. No tenant context exists yet at this point --
    this table deliberately has no RLS (see migration 055's docstring), the
    unique token_hash lookup plus these checks ARE the security boundary."""
    if not raw_token or not raw_token.startswith(_TOKEN_PREFIX):
        return None

    record = db.query(PersonalAccessToken).filter_by(token_hash=_hash(raw_token)).first()
    if not record or record.revoked_at is not None:
        return None
    if record.expires_at is not None:
        # SQLite (tests) returns naive datetimes on read-back even though the
        # column stores UTC; Postgres (prod) returns tz-aware. Normalize both
        # to aware-UTC before comparing so this works on either backend.
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None

    record.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return record


def list_tokens(db: Session, tenant_id: str, user_id: str) -> list[PersonalAccessToken]:
    return (
        db.query(PersonalAccessToken)
        .filter_by(tenant_id=tenant_id, user_id=user_id)
        .order_by(PersonalAccessToken.created_at.desc())
        .all()
    )


def revoke_token(db: Session, tenant_id: str, user_id: str, token_id: str) -> bool:
    """Revokes a token. Scoped to (tenant_id, user_id) so a user can only
    revoke their own tokens -- returns False if not found/not owned."""
    record = (
        db.query(PersonalAccessToken)
        .filter_by(id=token_id, tenant_id=tenant_id, user_id=user_id)
        .first()
    )
    if not record:
        return False
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True
