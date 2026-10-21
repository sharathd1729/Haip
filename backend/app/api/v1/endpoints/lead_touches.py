"""Where a lead came from (agency M6): measured first and last touch, and what the guest said.

GET /leads/{inquiry_id}/touches        first / last touch, the post or ad credited, the guest's own answer
PUT /leads/{inquiry_id}/heard-about    record "How did you first hear about us?" (leads.write; audited)
Not behind the Marketing Studio module: every workspace asks the question on the lead page.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import marketing_attribution as attribution
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

router = APIRouter(prefix="/leads", tags=["lead-touches"])


def _err(exc: MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": []})


def _view(v: dict) -> dict:
    def t(x):
        return None if x is None else {**x, "at": x["at"].isoformat() if x.get("at") else None}
    return {**v, "first": t(v["first"]), "last": t(v["last"]), "credited": t(v["credited"])}


@router.get("/{inquiry_id}/touches")
def touches(inquiry_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            _c=Depends(require_capability("leads.read"))):
    try:
        return _view(attribution.lead_view(db, user.tenant_id, inquiry_id))
    except MarketingError as exc:
        raise _err(exc)


class HeardAboutIn(BaseModel):
    heard_about: Optional[str] = Field(default=None, max_length=30)
    note: Optional[str] = Field(default=None, max_length=200)


@router.put("/{inquiry_id}/heard-about")
def heard_about(inquiry_id: str, body: HeardAboutIn, user: User = Depends(get_current_user),
                db: Session = Depends(get_db), _c=Depends(require_capability("leads.write"))):
    try:
        attribution.set_heard_about(db, user.tenant_id, inquiry_id, body.heard_about, body.note, user.id)
    except MarketingError as exc:
        raise _err(exc)
    db.commit()
    return _view(attribution.lead_view(db, user.tenant_id, inquiry_id))
