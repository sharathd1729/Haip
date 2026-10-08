"""Authentication for the public API: `Authorization: Bearer haip_live_...`."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.api_key import ApiKey
from app.services import api_key_service


class ApiError(HTTPException):
    """HTTPException carrying a machine-readable code, rendered as
    {"error": {"code": ..., "message": ...}} by the public app's handler."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code


_bearer = HTTPBearer(auto_error=False, description="Your HAIP API key, e.g. haip_live_... Create one in Settings > Developers.")


def get_api_key(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> ApiKey:
    raw = creds.credentials if creds else ""
    if not raw.strip():
        raise ApiError(401, "unauthorized", "Send your API key as 'Authorization: Bearer <key>'.",
                       headers={"WWW-Authenticate": "Bearer"})
    key = api_key_service.authenticate(db, raw.strip())
    if key is None:
        raise ApiError(401, "invalid_api_key", "This API key is invalid, expired or revoked.",
                       headers={"WWW-Authenticate": "Bearer"})
    request.state.api_key_id = key.id
    request.state.tenant_id = key.tenant_id
    return key


def require_scope(scope: str):
    def _check(key: ApiKey = Depends(get_api_key)) -> ApiKey:
        if scope not in (key.scopes or []):
            raise ApiError(403, "insufficient_scope", f"This API key does not have the '{scope}' scope.")
        return key
    return _check
