"""GET /work-queue -- the one list of what to do next.

Backs the My day screen, the dashboard's "Needs you now" cards and the
Calls call-back badge, so all three show the same numbers. See
app/services/work_queue_service.py for what goes in it.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import work_queue_service

router = APIRouter(prefix="/work-queue", tags=["work-queue"])


def _scope(current_user: User, mine_only: Optional[bool]) -> Optional[str]:
    """Agents always see their own work. Owners and managers see the team
    unless they ask for just theirs -- same rule the dashboard uses."""
    if current_user.role in (UserRole.OWNER, UserRole.MANAGER):
        return current_user.id if mine_only else None
    return current_user.id


def _tenant(db: Session, current_user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return tenant


@router.get("")
def get_work_queue(
    kinds: Optional[str] = Query(
        default=None,
        description="Comma-separated: callback, new_lead, reply, followup",
    ),
    mine_only: Optional[bool] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wanted = [k.strip() for k in kinds.split(",")] if kinds else None
    if wanted:
        unknown = [k for k in wanted if k not in work_queue_service.KINDS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown kind: {', '.join(unknown)}")
    return work_queue_service.build(
        db, _tenant(db, current_user), _scope(current_user, mine_only), kinds=wanted,
    )


@router.get("/counts")
def get_work_queue_counts(
    mine_only: Optional[bool] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return work_queue_service.counts(db, _tenant(db, current_user), _scope(current_user, mine_only))
