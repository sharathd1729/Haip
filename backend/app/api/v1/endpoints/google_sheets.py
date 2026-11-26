"""Send new leads to a Google Sheet (Settings > Integrations). No Google login: the owner pastes an Apps Script web app
address; see google_sheets_service.

  GET  /google-sheets        status: on/off, address hint, last row sent, last error   (owner, manager)
  PUT  /google-sheets        save the address and/or switch on/off                     (owner; audited)
  POST /google-sheets/test   send a test row now                                       (owner, manager)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.database import get_db, set_tenant_context
from app.models.user import User, UserRole
from app.services import google_sheets_service as gs

router = APIRouter(prefix="/google-sheets", tags=["google-sheets"])

_BAD_URL = ("That is not an Apps Script web app address. It looks like "
            "https://script.google.com/macros/s/AKfy.../exec (Deploy > New deployment > Web app).")


class SheetSettings(BaseModel):
    url: Optional[str] = Field(None, max_length=300)
    enabled: bool


@router.get("")
def get_settings(current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)), db: Session = Depends(get_db)):
    return gs.status(gs.get_row(db, current_user.tenant_id))


@router.put("")
def save_settings(body: SheetSettings, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    url = (body.url or "").strip() or None
    if url and not gs.valid_url(url):
        raise HTTPException(status_code=422, detail=_BAD_URL)
    try:
        row = gs.save(db, current_user.tenant_id, url, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="google_sheets.updated",
                 target_type="integration", target_id=row.id, payload={"enabled": body.enabled, "url_changed": bool(url)})
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    return gs.status(gs.get_row(db, current_user.tenant_id))


@router.post("/test")
def send_test(current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)), db: Session = Depends(get_db)):
    result = gs.send_test(db, current_user.tenant_id)
    db.commit()
    set_tenant_context(db, current_user.tenant_id)
    return {**result, **gs.status(gs.get_row(db, current_user.tenant_id))}
