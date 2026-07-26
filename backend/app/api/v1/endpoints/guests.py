import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.schemas.guest import GuestOut, GuestUpsertRequest, GuestUpdateRequest
from app.services.guest_service import upsert_by_phone, get_timeline, dpdp_delete
from app.services import guest_events_service
from app.schemas.guest_events import GuestJourneyResponse
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
    """
    Legacy Guest 360 timeline — calls and stays only, assembled per request.

    Superseded by /journey below, which reads the guest_events ledger and
    therefore also includes messages and stage changes. Kept unchanged because
    existing clients depend on this response shape.
    """
    return get_timeline(db, current_user.tenant_id, guest_id)


@router.get("/{guest_id}/journey", response_model=GuestJourneyResponse)
def guest_journey(
    guest_id: str,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Guest Journey — the guest's full history across every module, newest first.

    Reads the guest_events ledger rather than re-assembling from source tables,
    so it spans the whole lifecycle (messages, calls, stage changes, merges)
    and every inquiry the guest has ever had. The legacy /timeline endpoint
    queries conversations but never turns them into events, so messages are
    absent there entirely.

    Events only exist from the point the ledger started recording. Run
    tasks.backfill_guest_events for a tenant to populate history.
    """
    guest = (
        db.query(Guest)
        .filter_by(id=guest_id, tenant_id=current_user.tenant_id, is_deleted=False)
        .first()
    )
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    events, capped = guest_events_service.get_guest_timeline(
        db, current_user.tenant_id, guest_id, limit=limit
    )
    return GuestJourneyResponse(
        guest_id=guest_id,
        events=events,
        total_returned=len(events),
        capped=capped,
    )


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
    """
    D11: Initiate DPDP deletion with 30-day grace period.
    Sets guest to 'pending' state; hard-delete runs after 30 days by the nightly purge.
    """
    guest = db.query(Guest).filter_by(
        id=guest_id, tenant_id=current_user.tenant_id
    ).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    if guest.deletion_state == "pending":
        return {"status": "already_pending", "deletion_requested_at": guest.deletion_requested_at}

    now = datetime.now(timezone.utc).isoformat()
    guest.deletion_state = "pending"
    guest.deletion_requested_at = now
    guest.is_deleted = True  # hide from regular lists immediately

    append_audit(
        db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
        action="dpdp.delete_requested", target_type="guest", target_id=guest_id,
        payload={"deletion_requested_at": now},
    )
    db.commit()
    return {
        "status": "pending_deletion",
        "deletion_requested_at": now,
        "grace_period_days": 30,
        "hard_delete_after": "30 days",
    }


@router.post("/{guest_id}/dpdp/restore")
def dpdp_restore_guest(
    guest_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    """D11: Restore a guest from pending deletion (admin only, within 30-day window)."""
    guest = db.query(Guest).filter_by(
        id=guest_id, tenant_id=current_user.tenant_id
    ).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    if guest.deletion_state != "pending":
        raise HTTPException(status_code=400, detail="Guest is not pending deletion")

    guest.deletion_state = "none"
    guest.deletion_requested_at = None
    guest.is_deleted = False

    append_audit(
        db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
        action="dpdp.delete_restored", target_type="guest", target_id=guest_id,
    )
    db.commit()
    return {"status": "restored"}


@router.get("/dpdp/pending-deletions")
def list_pending_deletions(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    """D11: Admin queue — guests pending hard deletion."""
    from datetime import timedelta
    guests = (
        db.query(Guest)
        .filter_by(tenant_id=current_user.tenant_id, deletion_state="pending")
        .order_by(Guest.deletion_requested_at.asc())
        .all()
    )
    result = []
    for g in guests:
        req_at = g.deletion_requested_at
        days_left = None
        if req_at:
            try:
                req_dt = datetime.fromisoformat(req_at)
                hard_delete_dt = req_dt + timedelta(days=30)
                days_left = max(0, (hard_delete_dt - datetime.now(timezone.utc)).days)
            except Exception:
                pass
        result.append({
            "id": g.id,
            "name": g.name,
            "phone": g.phone[-4:] if g.phone else None,  # D13: mask
            "deletion_requested_at": req_at,
            "days_until_hard_delete": days_left,
        })
    return result
