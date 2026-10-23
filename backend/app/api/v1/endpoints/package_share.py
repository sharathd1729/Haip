"""Send package (package_share_service). conversations.send; scoped roles only on their own or unowned leads (404).

GET  /leads/{inquiry_id}/package-share   published retail packages (never b2b) with the exact message preview, and whether
                                         it can go now: window_open, template_approved, personal_bridge_only, has_phone
POST /leads/{inquiry_id}/package-share   {package_key}: text inside the 24 h window, else the approved template; refused
                                         (409/422 {code, message, text}) when it cannot, so the person can copy the text.
                                         Once per lead + package + IST day (a repeat answers status "duplicate"). Audited.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.leads import _visibility_scope
from app.core.database import get_db
from app.models.user import User
from app.services import package_share_service as svc
from app.services.authz_service import require_capability

router = APIRouter(prefix="/leads", tags=["leads360"])


class ShareIn(BaseModel):
    package_key: str = Field(min_length=1, max_length=80)


@router.get("/{inquiry_id}/package-share")
def package_options(inquiry_id: str, current_user: User = Depends(require_capability("conversations.send")),
                    db: Session = Depends(get_db)) -> dict:
    try:
        return svc.options(db, current_user, inquiry_id, scope_user_id=_visibility_scope(current_user))
    except svc.ShareError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())


@router.post("/{inquiry_id}/package-share", status_code=201)
def share_package(inquiry_id: str, body: ShareIn, current_user: User = Depends(require_capability("conversations.send")),
                  db: Session = Depends(get_db)) -> dict:
    try:
        return svc.share(db, current_user, inquiry_id, body.package_key, scope_user_id=_visibility_scope(current_user))
    except svc.ShareError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())
