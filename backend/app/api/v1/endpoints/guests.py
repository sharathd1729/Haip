import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.schemas.guest import GuestOut, GuestUpsertRequest, GuestUpdateRequest
from app.services.guest_service import upsert_by_phone, get_timeline, dpdp_delete
from app.core.audit import append_audit

router = APIRouter(prefix="/guests", tags=["guests"])


@router.get("", response_model=List[GuestOut])
def list_guests(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Guest).filter_by(tenant_id=current_user.tenant_id, is_deleted=False)
    if search:
        q = q.filter(
            (Guest.phone.ilike(f"%{search}%")) |
            (Guest.name.ilike(f"%{search}%")) |
            (Guest.email.ilike(f"%{search}%"))
        )
    return q.order_by(Guest.created_at.desc()).offset(offset).limit(limit).all()


@router.post("", response_model=GuestOut)
def upsert_guest(
    body: GuestUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    guest = upsert_by_phone(db, current_user.tenant_id, body.phone,
                            name=body.name, email=body.email, language_pref=body.language_pref)
    if body.tags:
        guest.tags = body.tags
    db.commit()
    db.refresh(guest)
    return guest


@router.get("/{guest_id}", response_model=GuestOut)
def get_guest(
    guest_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=current_user.tenant_id, is_deleted=False).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest


@router.get("/{guest_id}/timeline")
def guest_timeline(
    guest_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_timeline(db, current_user.tenant_id, guest_id)


@router.patch("/{guest_id}", response_model=GuestOut)
def update_guest(
    guest_id: str,
    body: GuestUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=current_user.tenant_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(guest, k, v)
    db.commit()
    db.refresh(guest)
    return guest


@router.post("/{guest_id}/dpdp/delete")
def dpdp_delete_guest(
    guest_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    result = dpdp_delete(db, current_user.tenant_id, guest_id)
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                 action="dpdp.delete", target_type="guest", target_id=guest_id)
    db.commit()
    return result
