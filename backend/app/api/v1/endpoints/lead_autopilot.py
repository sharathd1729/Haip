"""Lead autopilot API.

  GET  /lead-autopilot/settings           owner, manager   mode, threshold, timings + 30-day counts
  PUT  /lead-autopilot/settings           owner only       audited (lead_autopilot.settings_changed, before/after)
  POST /leads/{inquiry_id}/autopilot/undo leads.write      put the lead back before one automatic move (audited)
  POST /leads/{inquiry_id}/autopilot/pin  leads.write      pin/unpin: the autopilot leaves a pinned lead alone (audited)

No LLM here: decisions are made by the lead_autopilot Celery tasks. Lead visibility matches GET /leads/{id}: a non
owner/manager only reaches their own and unassigned leads (404 otherwise, like a lead of another tenant).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.inquiry import Inquiry
from app.models.user import User, UserRole
from app.schemas.lead_autopilot import AutopilotSettingsOut, AutopilotSettingsUpdate, PinRequest, UndoRequest
from app.services import lead_autopilot_service as svc
from app.services import lead_autopilot_view
from app.services.authz_service import require_capability

router = APIRouter(tags=["lead-autopilot"])


@router.get("/lead-autopilot/settings", response_model=AutopilotSettingsOut)
def get_settings(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    return AutopilotSettingsOut(**svc.get_settings(db, tid), **svc.settings_stats(db, tid))


@router.put("/lead-autopilot/settings", response_model=AutopilotSettingsOut)
def put_settings(
    body: AutopilotSettingsUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    tid = current_user.tenant_id
    after = svc.update_settings(db, tid, current_user.id, body.model_dump(exclude_none=True))
    db.commit()
    return AutopilotSettingsOut(**after, **svc.settings_stats(db, tid))


def _visible_inquiry(db: Session, user: User, inquiry_id: str) -> Inquiry:
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    if inquiry is None or (
        user.role not in (UserRole.OWNER, UserRole.MANAGER) and inquiry.assigned_to not in (None, user.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return inquiry


@router.post("/leads/{inquiry_id}/autopilot/undo")
def undo_move(
    inquiry_id: str,
    body: UndoRequest,
    current_user: User = Depends(require_capability("leads.write")),
    db: Session = Depends(get_db),
):
    inquiry = _visible_inquiry(db, current_user, inquiry_id)
    try:
        svc.undo(db, current_user.tenant_id, inquiry, body.event_id, current_user.id)
    except svc.AutopilotActionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    db.refresh(inquiry)
    return lead_autopilot_view.lead_block(db, current_user.tenant_id, inquiry)


@router.post("/leads/{inquiry_id}/autopilot/pin")
def pin_lead(
    inquiry_id: str,
    body: PinRequest,
    current_user: User = Depends(require_capability("leads.write")),
    db: Session = Depends(get_db),
):
    inquiry = _visible_inquiry(db, current_user, inquiry_id)
    svc.set_pinned(db, current_user.tenant_id, inquiry, current_user.id, body.pinned)
    db.commit()
    db.refresh(inquiry)
    return lead_autopilot_view.lead_block(db, current_user.tenant_id, inquiry)
