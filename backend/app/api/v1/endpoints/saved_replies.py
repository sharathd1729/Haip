import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.saved_reply import SavedReply

router = APIRouter(prefix="/saved-replies", tags=["saved-replies"])


class SavedReplyOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    tenant_id: str
    user_id: Optional[str] = None
    created_by: str
    title: str
    body: str
    language: str = "en"
    usage_count: int = 0


class SavedReplyCreate(BaseModel):
    title: str
    body: str
    language: str = "en"
    user_id: Optional[str] = None   # null → tenant-shared (admin only)


class SavedReplyUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    language: Optional[str] = None
    user_id: Optional[str] = None


@router.get("", response_model=List[SavedReplyOut])
def list_saved_replies(
    q: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(SavedReply).filter_by(tenant_id=current_user.tenant_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (SavedReply.title.ilike(like)) | (SavedReply.body.ilike(like))
        )
    return (
        query.order_by(SavedReply.usage_count.desc(), SavedReply.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("", response_model=SavedReplyOut, status_code=201)
def create_saved_reply(
    body: SavedReplyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reply = SavedReply(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        user_id=body.user_id,
        created_by=current_user.id,
        title=body.title,
        body=body.body,
        language=body.language,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)
    return reply


@router.patch("/{reply_id}", response_model=SavedReplyOut)
def update_saved_reply(
    reply_id: str,
    body: SavedReplyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reply = db.query(SavedReply).filter_by(id=reply_id, tenant_id=current_user.tenant_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Saved reply not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(reply, k, v)
    db.commit()
    db.refresh(reply)
    return reply


@router.delete("/{reply_id}", status_code=204)
def delete_saved_reply(
    reply_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reply = db.query(SavedReply).filter_by(id=reply_id, tenant_id=current_user.tenant_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Saved reply not found")
    db.delete(reply)
    db.commit()


@router.post("/{reply_id}/use", response_model=SavedReplyOut)
def increment_usage(
    reply_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reply = db.query(SavedReply).filter_by(id=reply_id, tenant_id=current_user.tenant_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Saved reply not found")
    reply.usage_count = (reply.usage_count or 0) + 1
    db.commit()
    db.refresh(reply)
    return reply
