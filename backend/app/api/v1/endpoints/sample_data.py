"""
O2 / O9 — Sample-data endpoints.

POST /sample-data/seed      — seeds full sample dataset (O2)
POST /sample-data/seed/welcome — seeds single welcome conversation (O9)
POST /sample-data/wipe      — deletes all is_sample rows
GET  /sample-data/status    — returns { has_sample: bool, counts: {...} }
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.guest import Guest
from app.models.conversation import Conversation
from app.models.call import Call
from app.services.sample_data import (
    seed_sample_data,
    seed_welcome_conversation,
    wipe_sample_data,
    has_sample_data,
)
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/sample-data", tags=["sample-data"])


@router.get("/status")
def get_sample_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return whether sample data exists for this tenant."""
    tid = current_user.tenant_id
    present = has_sample_data(db, tid)

    counts = {}
    if present:
        counts["guests"] = db.query(Guest).filter_by(tenant_id=tid, is_sample=True).count()
        counts["conversations"] = db.query(Conversation).filter_by(tenant_id=tid, is_sample=True).count()
        counts["calls"] = db.query(Call).filter_by(tenant_id=tid, is_sample=True).count()

    return {"has_sample": present, "counts": counts}


@router.post("/seed", status_code=status.HTTP_201_CREATED)
def seed(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Seed full sample dataset. Idempotent — safe to call if already seeded."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owners can seed sample data")

    if has_sample_data(db, current_user.tenant_id):
        return {"message": "Sample data already present. Wipe first to re-seed.", "already_present": True}

    counts = seed_sample_data(db, current_user.tenant_id)
    log.info("sample_data_seeded", tenant_id=current_user.tenant_id, **counts)
    return {"message": "Sample data seeded", "counts": counts, "already_present": False}


@router.post("/seed/welcome", status_code=status.HTTP_201_CREATED)
def seed_welcome(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """O9: Seed a single welcome conversation. Used post-onboarding for first-time dashboard."""
    if has_sample_data(db, current_user.tenant_id):
        return {"message": "Sample data already present", "already_present": True}

    conv_id = seed_welcome_conversation(db, current_user.tenant_id)
    return {"message": "Welcome conversation seeded", "conversation_id": conv_id, "already_present": False}


@router.post("/wipe", status_code=status.HTTP_200_OK)
def wipe(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete all sample data for this tenant."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owners can wipe sample data")

    counts = wipe_sample_data(db, current_user.tenant_id)
    return {"message": "Sample data wiped", "deleted": counts}
