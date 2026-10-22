"""Log a call made outside HAIP (CRM fixes, 22 Oct 2026).

POST /leads/{inquiry_id}/log-call   a call from the agent's own phone: outcome connected | no_answer | voicemail, optional
                                    note and minutes (leads.write; scoped roles only on their own or unowned leads; audited
                                    call.logged_manually). A connected call closes the guest's call-back reminders.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.leads import _visibility_scope
from app.core.database import get_db
from app.models.user import User
from app.services import lead_call_log
from app.services.authz_service import require_capability

router = APIRouter(prefix="/leads", tags=["leads360"])


class LogCallIn(BaseModel):
    outcome: Literal["connected", "no_answer", "voicemail"]
    note: Optional[str] = Field(default=None, max_length=500)
    duration_minutes: Optional[int] = Field(default=None, ge=0, le=600)


@router.post("/{inquiry_id}/log-call", status_code=201)
def log_call(inquiry_id: str, body: LogCallIn, current_user: User = Depends(require_capability("leads.write")),
             db: Session = Depends(get_db)) -> dict:
    try:
        out = lead_call_log.log_call(db, current_user, inquiry_id, outcome=body.outcome, note=body.note,
                                     duration_minutes=body.duration_minutes, scope_user_id=_visibility_scope(current_user))
    except lead_call_log.LogCallError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    db.commit()
    return out
